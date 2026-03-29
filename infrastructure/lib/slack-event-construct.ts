import {
  AuthorizationType, LambdaIntegration, LambdaRestApi,
  LogGroupLogDestination, MethodLoggingLevel, PassthroughBehavior,
  ResponseType, ThrottleSettings,
} from "aws-cdk-lib/aws-apigateway";
import { Function as LambdaFunction, Code, Runtime, Tracing, Alias } from "aws-cdk-lib/aws-lambda";
import { Effect, ManagedPolicy, PolicyDocument, PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";
import { Duration, Stack } from "aws-cdk-lib";
import { Queue, QueueEncryption } from "aws-cdk-lib/aws-sqs";
import { Key } from "aws-cdk-lib/aws-kms";
import { SqsEventSource } from "aws-cdk-lib/aws-lambda-event-sources";
import { CfnWebACL, CfnWebACLAssociation } from "aws-cdk-lib/aws-wafv2";
import { Secret } from "aws-cdk-lib/aws-secretsmanager";
import { DefaultWebAcl } from "./web-acl";

const DEFAULT_THROTTLE: ThrottleSettings = { burstLimit: 50, rateLimit: 20 };

const SECURITY_HEADERS: Record<string, string> = {
  "Strict-Transport-Security": "'max-age=31536000'",
  "X-Content-Type-Options": "'nosniff'",
  "X-XSS-Protection": "'1; mode=block'",
  "X-Frame-Options": "'SAMEORIGIN'",
  "Referrer-Policy": "'no-referrer'",
};

interface SlackEventNotificationProps {
  prefix: string;
  actionLambda?: LambdaFunction;
  tracingActive?: boolean;
  wafWebACL?: CfnWebACL | null;
  queueVisibilityTimeout?: Duration;
  maxReceiveCount?: number;
  receiptLambdaProvisionedConcurrency?: number;
}

export class SlackEventNotification extends Construct {
  readonly receiptLambda: LambdaFunction;
  readonly actionLambda: LambdaFunction;
  readonly messageQueue: Queue;
  readonly deadLetterQueue: Queue;
  readonly api: LambdaRestApi;
  readonly wafACL: CfnWebACL | null;

  constructor(scope: Construct, id: string, props: SlackEventNotificationProps) {
    super(scope, id);

    const thisStack = Stack.of(this);
    const tracing = props.tracingActive ? Tracing.ACTIVE : Tracing.DISABLED;

    const createRole = (name: string): Role =>
      new Role(this, `${props.prefix}${name}Role`, {
        roleName: `${props.prefix}${name}Role`,
        assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
        managedPolicies: [ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole")],
        inlinePolicies: {
          XRay: new PolicyDocument({
            statements: [new PolicyStatement({ effect: Effect.ALLOW, actions: ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], resources: ["*"] })],
          }),
        },
      });

    this.receiptLambda = new LambdaFunction(this, "ReceiptLambda", {
      functionName: `${props.prefix}ReceiptLambda`,
      runtime: Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: Code.fromInline(`
        const crypto = require("crypto");
        const { SQSClient, SendMessageCommand } = require("@aws-sdk/client-sqs");
        const { SecretsManagerClient, GetSecretValueCommand } = require("@aws-sdk/client-secrets-manager");
        let signingKey;
        const sqs = new SQSClient();
        const sm = new SecretsManagerClient();
        exports.handler = async (event) => {
          if (!signingKey) {
            const secret = await sm.send(new GetSecretValueCommand({ SecretId: process.env.SECRETS_ARN }));
            signingKey = JSON.parse(secret.SecretString).SLACK_SIGNING_SECRET;
          }
          const ts = event.headers["X-Slack-Request-Timestamp"];
          if (Math.abs(Date.now() / 1000 - ts) > 300) throw "403";
          const sig = "v0=" + crypto.createHmac("sha256", signingKey).update("v0:" + ts + ":" + JSON.stringify(event.rawBody).replace(/\\//g, "\\\\/"), "utf8").digest("hex");
          if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(event.headers["X-Slack-Signature"]))) throw "403";
          if (event.body.challenge) return { challenge: event.body.challenge };
          await sqs.send(new SendMessageCommand({ MessageBody: JSON.stringify(event.body), QueueUrl: process.env.QUEUE_URL }));
          return {};
        };
      `),
      tracing,
      timeout: Duration.minutes(1),
      role: createRole("Receipt"),
      logRetention: RetentionDays.ONE_YEAR,
    });

    this.actionLambda = props.actionLambda ?? new LambdaFunction(this, "ActionLambda", {
      functionName: `${props.prefix}ActionLambda`,
      runtime: Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: Code.fromInline('exports.handler = (event, ctx, cb) => cb(null, "ok");'),
      tracing,
      timeout: Duration.minutes(1),
      role: createRole("Action"),
      logRetention: RetentionDays.ONE_YEAR,
    });

    const signingSecret = new Secret(this, "SigningSecret", {
      secretName: `${props.prefix}/slack-signing-secret`,
      generateSecretString: { secretStringTemplate: JSON.stringify({}), generateStringKey: "SLACK_SIGNING_SECRET" },
    });

    signingSecret.grantRead(this.receiptLambda);
    signingSecret.grantRead(this.actionLambda);
    this.receiptLambda.addEnvironment("SECRETS_ARN", signingSecret.secretArn);

    const encryptionKey = new Key(this, "QueueKey", { enableKeyRotation: true });
    encryptionKey.grantEncrypt(this.receiptLambda.role!);
    encryptionKey.grantEncryptDecrypt(this.actionLambda.role!);

    this.deadLetterQueue = new Queue(this, "DeadLetterQueue", {
      queueName: `${props.prefix}DeadLetterQueue`,
      encryption: QueueEncryption.KMS,
      encryptionMasterKey: encryptionKey,
    });

    this.messageQueue = new Queue(this, "MessageQueue", {
      queueName: `${props.prefix}MessageQueue`,
      encryption: QueueEncryption.KMS,
      encryptionMasterKey: encryptionKey,
      visibilityTimeout: props.queueVisibilityTimeout ?? Duration.seconds(60),
      deadLetterQueue: { maxReceiveCount: props.maxReceiveCount ?? 3, queue: this.deadLetterQueue },
    });

    this.messageQueue.grantSendMessages(this.receiptLambda.role!);
    this.receiptLambda.addEnvironment("QUEUE_URL", this.messageQueue.queueUrl);
    this.actionLambda.addEnvironment("QUEUE_URL", this.messageQueue.queueUrl);
    this.actionLambda.addEventSource(new SqsEventSource(this.messageQueue, { batchSize: 1, enabled: true }));

    const accessLogGroup = new LogGroup(this, "AccessLogs", {
      logGroupName: `/aws/apigateway/accesslogs/${props.prefix}`,
      retention: RetentionDays.FIVE_YEARS,
    });

    this.api = new LambdaRestApi(this, "ReceiptApi", {
      restApiName: `${props.prefix}ReceiptApi`,
      handler: this.receiptLambda,
      deploy: true,
      proxy: false,
      deployOptions: {
        stageName: "prod",
        throttlingBurstLimit: DEFAULT_THROTTLE.burstLimit,
        throttlingRateLimit: DEFAULT_THROTTLE.rateLimit,
        tracingEnabled: props.tracingActive,
        metricsEnabled: true,
        loggingLevel: MethodLoggingLevel.INFO,
        accessLogDestination: new LogGroupLogDestination(accessLogGroup),
      },
    });

    this.api.addGatewayResponse("Default4xx", {
      type: ResponseType.DEFAULT_4XX,
      responseHeaders: SECURITY_HEADERS,
    });
    this.api.addGatewayResponse("Default5xx", {
      type: ResponseType.DEFAULT_5XX,
      responseHeaders: SECURITY_HEADERS,
    });

    this.api.root.addMethod("POST", new LambdaIntegration(this.receiptLambda, {
      proxy: false,
      passthroughBehavior: PassthroughBehavior.WHEN_NO_TEMPLATES,
      requestTemplates: {
        "application/json": `{ "body": $input.json('$'), "rawBody": $input.json('$'), "headers": { #foreach($param in $input.params().header.keySet()) "$param": "$util.escapeJavaScript($input.params().header.get($param))" #if($foreach.hasNext),#end #end } }`,
      },
      integrationResponses: [
        { statusCode: "200" },
        { statusCode: "400", selectionPattern: "400.*" },
        { statusCode: "403", selectionPattern: "403.*" },
        { statusCode: "503", selectionPattern: "503.*" },
      ],
    }), {
      authorizationType: AuthorizationType.NONE,
      requestParameters: {
        "method.request.header.X-Slack-Request-Timestamp": true,
        "method.request.header.X-Slack-Signature": true,
      },
      methodResponses: [{ statusCode: "200" }, { statusCode: "400" }, { statusCode: "403" }, { statusCode: "503" }],
    });

    if (props.wafWebACL !== null) {
      this.wafACL = props.wafWebACL ?? new DefaultWebAcl(scope).acl;
      new CfnWebACLAssociation(scope, "SlackWebACL", {
        webAclArn: this.wafACL.attrArn,
        resourceArn: `arn:${thisStack.partition}:apigateway:${thisStack.region}::/restapis/${this.api.restApiId}/stages/${this.api.deploymentStage.stageName}`,
      });
    } else {
      this.wafACL = null;
    }
  }
}
