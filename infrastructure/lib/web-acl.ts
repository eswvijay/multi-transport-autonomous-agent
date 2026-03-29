import { CfnWebACL } from "aws-cdk-lib/aws-wafv2";
import { Construct } from "constructs";

const MANAGED_RULES = [
  "AWSManagedRulesAmazonIpReputationList",
  "AWSManagedRulesKnownBadInputsRuleSet",
  "AWSManagedRulesCommonRuleSet",
  "AWSManagedRulesLinuxRuleSet",
  "AWSManagedRulesSQLiRuleSet",
];

export class DefaultWebAcl {
  readonly acl: CfnWebACL;

  constructor(scope: Construct) {
    this.acl = new CfnWebACL(scope, "DefaultWebACL", {
      defaultAction: { allow: {} },
      scope: "REGIONAL",
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: "AgentSlackACL",
      },
      rules: MANAGED_RULES.map((name, priority) => ({
        name: `AWS-${name}`,
        priority,
        statement: { managedRuleGroupStatement: { vendorName: "AWS", name } },
        overrideAction: { none: {} },
        visibilityConfig: {
          sampledRequestsEnabled: true,
          cloudWatchMetricsEnabled: true,
          metricName: `AWS-${name}`,
        },
      })),
    });
  }
}
