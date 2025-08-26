flowchart TB
  %% VPC
  subgraph VPC[ApiGW VPC]
    vpc[ApiGW VPC]
    
    %% Public Subnets
    subgraph PublicSubnets[Public Subnets]
      pub1[Subnet1\nEC2::Subnet]
      pub2[Subnet2\nEC2::Subnet]
      igw[InternetGateway]
      nat1[NAT Gateway]
      
      pub1 --> vpc
      pub2 --> vpc
      nat1 --> pub1
      nat1 --> pub2
      pub1 --> igw
      pub2 --> igw
    end

    %% Private Subnets
    subgraph PrivateSubnets[Private Subnets]
      priv1[Subnet1\nEC2::Subnet]
      priv2[Subnet2\nEC2::Subnet]
      priv1 --> vpc
      priv2 --> vpc
    end

    %% Flow Logs
    flowlogs[FlowLog\nEC2::FlowLog]
    flowlogs --> vpc
  end

  %% API Gateway
  subgraph APIGW[API Gateway]
    api[ApiGWFanAPI\nRestApi]
    deploy[Deployment]
    stage[Stage: prod]
    
    deploy --> api
    stage --> deploy
    stage --> api
  end

  %% SQS / SNS
  subgraph Messaging[Messaging]
    sns[Fan Topic\nSNS::Topic]
    sqs1[CreatedStatusQueue\nSQS::Queue]
    sqs2[OtherStatusQueue\nSQS::Queue]

    sns --> sqs1
    sns --> sqs2
  end

  %% Connections
  api --> sns
  priv1 --> nat1
  priv2 --> nat1
