import { App, Stack, StackProps } from "aws-cdk-lib";
import { Construct } from "constructs";
import { SlackEventNotification } from "./slack-event-construct";

class AgentInfraStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    new SlackEventNotification(this, "SlackBot", {
      prefix: "AutonomousAgent",
      tracingActive: true,
    });
  }
}

const app = new App();
new AgentInfraStack(app, "AgentInfra", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? "us-east-1",
  },
});
