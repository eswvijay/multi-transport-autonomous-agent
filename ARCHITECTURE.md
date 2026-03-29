# Architecture

## System Overview — Transport Adapter Pattern

```mermaid
graph TB
    subgraph AgentCore["Agent Core (Python)"]
        AGENT[Strands Agent<br/>BedrockModel + Claude Sonnet 4]
        SEC[Security Layer<br/>Token wrapping + injection defense]
        MEM[Session Manager<br/>DynamoDB + guardrails]
        GW[GatewayToolPool<br/>Dynamic tool loading]
        TOOLS[Tools Registry<br/>KB Query, Jira, Forum, Vision AI]
        CA[CloudAuth<br/>OAuth2 token exchange]
    end

    subgraph Transports["4 Transport Adapters"]
        AGUI[AG-UI Transport<br/>FastAPI SSE + state sync]
        SLACK[Slack Transport<br/>SQS → Lambda + thread sessions]
        MCP[MCP Transport<br/>stdio server + write safety]
        API[REST API Transport<br/>Lambda / HTTP POST]
    end

    subgraph Surfaces["User Interfaces"]
        WEB[Web Browser<br/>React / Next.js]
        SLACK_APP[Slack App<br/>Events API]
        IDE[IDE Extensions<br/>Cline / Cursor / Q]
        AUTO[Automation<br/>CI/CD / Cron / Webhooks]
    end

    subgraph Infrastructure["CDK Infrastructure"]
        APIGW[API Gateway<br/>+ WAF + HSTS]
        SQS[SQS Queue<br/>KMS encrypted + DLQ]
        RECEIPT[Receipt Lambda<br/>Slack HMAC-SHA256 verification]
        ACTION[Action Lambda<br/>Agent invocation]
        DDB[DynamoDB<br/>Session store + TTL]
    end

    AGENT --> SEC --> MEM
    AGENT --> GW --> TOOLS
    AGENT --> CA

    AGUI -->|stream_async| AGENT
    SLACK -->|invoke_runtime| AGENT
    MCP -->|SigV4 HTTPS| AGENT
    API -->|invoke_agent| AGENT

    WEB -->|SSE POST| AGUI
    SLACK_APP -->|Events API| APIGW
    IDE -->|stdio| MCP
    AUTO -->|HTTP POST| API

    APIGW --> RECEIPT --> SQS --> ACTION --> SLACK
    SLACK --> DDB
```

## AG-UI Transport — Event Flow

```mermaid
sequenceDiagram
    participant Browser as Web Browser
    participant FastAPI as FastAPI Endpoint
    participant Adapter as AgUiAgentAdapter
    participant Agent as Strands Agent
    participant KB as Knowledge Bases

    Browser->>FastAPI: POST / (RunAgentInput)
    FastAPI->>Adapter: agent.run(input_data)
    
    Adapter->>Adapter: Sync proxy tools from client
    Adapter-->>Browser: RunStartedEvent
    Adapter-->>Browser: StateSnapshotEvent
    
    Adapter->>Agent: stream_async(user_message)
    
    loop Streaming Events
        Agent->>KB: Tool call (query_knowledge_base)
        KB-->>Agent: Results
        Agent-->>Adapter: {"current_tool_use": ...}
        Adapter-->>Browser: ToolCallStartEvent
        Adapter-->>Browser: ToolCallArgsEvent
        Adapter-->>Browser: ToolCallEndEvent
        
        Agent-->>Adapter: {"data": "Analysis shows..."}
        Adapter-->>Browser: TextMessageContentEvent
    end
    
    Adapter-->>Browser: TextMessageEndEvent
    Adapter-->>Browser: RunFinishedEvent
    
    Note over Adapter,Agent: finally: agent_stream.aclose()
```

## Slack Transport — Message Flow

```mermaid
sequenceDiagram
    participant User as Slack User
    participant Slack as Slack API
    participant APIGW as API Gateway + WAF
    participant Receipt as Receipt Lambda
    participant SQS as SQS Queue
    participant Action as Action Lambda
    participant Runtime as Agent Runtime
    participant DDB as DynamoDB Sessions

    User->>Slack: @bot What caused the crash?
    Slack->>APIGW: POST /prod (Events API)
    APIGW->>Receipt: Lambda invocation
    
    Receipt->>Receipt: Verify HMAC-SHA256 signature
    Receipt->>Receipt: Check timestamp (< 5 min)
    Receipt->>SQS: SendMessage(event body)
    Receipt-->>APIGW: 200 OK (< 3 seconds)
    APIGW-->>Slack: 200 OK
    
    SQS->>Action: Trigger (batchSize: 1)
    Action->>Action: Strip bot mentions
    Action->>Action: Download attached files → S3
    Action->>DDB: Get existing session_id for thread
    
    Action->>Runtime: SigV4-signed POST /invocations
    Runtime-->>Action: SSE stream (chunked)
    Action->>Action: parse_sse_response()
    
    Action->>DDB: Save session_id for thread
    Action->>Slack: chat.postMessage (chunked ≤ 4000 chars)
    Slack-->>User: Agent response in thread
```

## MCP Transport — Write Safety Flow

```mermaid
stateDiagram-v2
    [*] --> ReceiveMessage: IDE sends ask-agent
    
    ReceiveMessage --> CheckWriteIntent: Analyze message
    
    CheckWriteIntent --> ExecuteDirectly: No write patterns matched
    CheckWriteIntent --> CheckConfirmFlag: Write intent detected
    
    CheckConfirmFlag --> BlockWithError: confirm_write ≠ true
    CheckConfirmFlag --> ExecuteWithApproval: confirm_write = true
    
    BlockWithError --> [*]: Return safety error message
    
    ExecuteDirectly --> InvokeRuntime: SigV4 sign + POST
    ExecuteWithApproval --> InvokeRuntime: SigV4 sign + POST
    
    InvokeRuntime --> ParseSSE: Read streaming response
    ParseSSE --> ReturnResult: Extract text deltas
    ReturnResult --> [*]

    note right of CheckWriteIntent
        WRITE_PATTERNS:
        /create.*ticket/i
        /update.*issue/i
        /resolve.*ticket/i
        /close.*issue/i
        /add comment/i
    end note
```

## Agent Core — Security Model

```mermaid
graph LR
    subgraph Input["User Input"]
        RAW[Raw message from any transport]
    end

    subgraph Security["Security Pipeline"]
        S1[sanitize_input<br/>5 regex patterns<br/>null byte removal]
        S2[wrap_untrusted_input<br/>XML token wrapping]
        S3[System Prompt<br/>Security protocol embedded]
    end

    subgraph Agent["Agent Processing"]
        LLM[BedrockModel<br/>Claude Sonnet 4<br/>64K tokens<br/>anthropic_beta: context-1m]
    end

    RAW --> S1 --> S2 --> S3 --> LLM

    subgraph Patterns["Filtered Patterns"]
        P1["ignore previous instructions"]
        P2["you are now a different"]
        P3["system:"]
        P4["forget everything"]
        P5["override system/instructions"]
    end

    Patterns -.->|removed by| S1
```

## Session Management

```mermaid
graph TB
    subgraph "Session Lifecycle"
        NEW[New Request] --> BUILD[build_runtime_session_id<br/>actor___session]
        BUILD --> CHECK{Agent exists?}
        
        CHECK -->|No| CREATE[Create Agent<br/>Pin to session]
        CHECK -->|Yes, same session| REUSE[Reuse Agent]
        CHECK -->|Yes, different session| REJECT[Raise ValueError<br/>Container pinned]
        
        CREATE --> MEMORY[Load history from DynamoDB]
        MEMORY --> GUARDRAIL[Apply guardrails<br/>Max 100K chars<br/>XSS filtering]
        GUARDRAIL --> INVOKE[Agent.stream_async]
        
        REUSE --> INVOKE
        INVOKE --> SAVE[Save history<br/>Max 50 messages<br/>Trimmed FIFO]
    end

    subgraph "Slack Thread Sessions"
        THREAD[Slack thread_ts] --> DDB_LOOKUP[DynamoDB lookup<br/>channel_id + thread_ts]
        DDB_LOOKUP --> SESSION_ID[Retrieve session_id]
        SESSION_ID --> RUNTIME[Pass to runtime_client]
        RUNTIME --> DDB_SAVE[Save updated session_id<br/>TTL: 24 hours]
    end
```

## Infrastructure — CDK Slack Construct

```mermaid
graph TD
    subgraph "SlackEventNotification Construct"
        APIGW[API Gateway<br/>REST API + throttle 50/20]
        
        WAF[WAF Web ACL<br/>5 AWS Managed Rules<br/>• IP Reputation<br/>• Known Bad Inputs<br/>• Common Rules<br/>• Linux Rules<br/>• SQLi Rules]
        
        RECEIPT[Receipt Lambda<br/>Node.js 20<br/>Slack HMAC verification<br/>Challenge handling]
        
        KMS[KMS Key<br/>Rotation enabled]
        
        SQS[SQS Queue<br/>KMS encrypted<br/>Visibility: 60s]
        
        DLQ[Dead Letter Queue<br/>KMS encrypted<br/>Max receive: 3]
        
        ACTION[Action Lambda<br/>Custom logic<br/>SQS event source]
        
        SECRET[Secrets Manager<br/>SLACK_SIGNING_SECRET]
        
        LOGS[CloudWatch Logs<br/>Access logs: 5 years<br/>Lambda logs: 1 year]
    end
    
    WAF -->|protects| APIGW
    APIGW -->|POST /| RECEIPT
    RECEIPT -->|verify + forward| SQS
    SQS -->|trigger| ACTION
    SQS -->|overflow| DLQ
    KMS -->|encrypts| SQS
    KMS -->|encrypts| DLQ
    SECRET -->|read by| RECEIPT
    SECRET -->|read by| ACTION
    APIGW -->|access logs| LOGS

    subgraph "Security Headers"
        H1[Strict-Transport-Security]
        H2[X-Content-Type-Options: nosniff]
        H3[X-XSS-Protection]
        H4[X-Frame-Options: SAMEORIGIN]
        H5[Referrer-Policy: no-referrer]
    end
```

## Tool Registry — Agent-Side Tools

```mermaid
graph LR
    subgraph "Tool Registry"
        REG[ToolRegistry<br/>register/get/invoke/list]
    end

    subgraph "Builtin Tools"
        CALC[calculator<br/>strands_tools]
        HTTP[http_request<br/>strands_tools]
        HEALTH[health_check<br/>connectivity test]
    end

    subgraph "Domain Tools"
        KB[query_knowledge_base<br/>4 Bedrock KBs<br/>Vector search + scoring]
        JIRA_S[search_jira<br/>JQL queries]
        JIRA_C[create_jira_issue<br/>Project + type + priority]
        FORUM_T[get_forum_topic<br/>Discourse API]
        FORUM_S[search_forum_topics<br/>Keyword + category]
        FORUM_ST[get_forum_stats<br/>User/topic/post counts]
        VISION[analyze_media<br/>Bedrock Vision AI<br/>S3 or local images]
    end

    subgraph "Dynamic Tools"
        GW[GatewayToolPool<br/>Loaded from env modules]
        PROXY[AG-UI Proxy Tools<br/>Client-defined, runtime]
    end

    REG --> CALC & HTTP & HEALTH
    REG --> KB & JIRA_S & JIRA_C
    REG --> FORUM_T & FORUM_S & FORUM_ST & VISION
    REG --> GW & PROXY
```
