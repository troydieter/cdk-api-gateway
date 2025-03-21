
# An AWS Well-Architected Deployment of an AWS API-Gateway + Fanout

## Simplified Diagram
![cad_diagram](img/cad_diagram.jpg)

## Programmatic Diagram (rendered using cdk-dia)
![diagram](img/diagram.png)
## Overview
This solution will deploy an AWS API Gateway, multiple AWS SNS topics and AWS SQS queues that will fan out incoming requests. It will utilize a custom domain and certificate
for incoming requests.

## Pre-requisites 
1. An Amazon Route 53 (public) forward zone, that has its respective nameservers pointed to it (e.g. you've registered a domain with your preferred registrar and have pointed the `nameserver` entries to the Amazon Route53 public forward zone)
2. An Amazon Certificate Manager wildcard certificate (OR a certificate issued to the `custom_domain_name` value set in `cdk.json`) issued to the value `hosted_zone_name` in `cdk.json`
3. Set the following in `cdk.json`:
   1. Set the Amazon Route53 forward `zone name` that was defined in step #1 (e.g. `troydieter.com`) as `hosted_zone_name`
   2. Set the Amazon Route53 forward `ID` name that was defined in step #1 as `hosted_zone_id` 
   3. Set the Amazon Certificate Manager `ARN` defined in step #2 as `cert_arn`
   4. Set the `custom_domain_name` to the preferred custom domain name, that aligns to the value set in `3.1` (e.g. api.troydieter.com)
   5. Set the `alarm_email` to your email address, which will subscribe to the Amazon SNS topic that handles alerts

If you have any questions, need clarification a step -- please open a Github issue! I'm always open to feedback and here to help.

### Message Handling

In this example we have an API Gateway with a "/SendEvent" endpoint that takes a POST request with a JSON payload. The payload formats are beneath.

When API Gateway receives the json it automatically through VTL routes it to an SNS Topic, this Topic then has two subscribers which are SQS Queues. The difference between the two subscribers is that one looks for a property of "status":"created" in the json and the other subscriber looks for any message that doesn't have that property. Each queue has a lambda that subscribes to it and prints whatever message it recieves to cloudwatch.

### JSON Payload Format

To send to the first lambda
`{ "message": "hello", "status": "created" }`

To send to the second lambda
`{ "message": "hello", "status": "not created" }`

### Postman Example
![postman](img/postman.png)

## Useful CDK Commands

The `cdk.json` file tells the CDK Toolkit how to execute your app.

This project is set up like a standard Python project.  The initialization
process also creates a virtualenv within this project, stored under the .env
directory.  To create the virtualenv it assumes that there is a `python3`
(or `python` for Windows) executable in your path with access to the `venv`
package. If for any reason the automatic creation of the virtualenv fails,
you can create the virtualenv manually.

To manually create a virtualenv on MacOS and Linux:

```
$ python3 -m venv .env
```

After the init process completes and the virtualenv is created, you can use the following
step to activate your virtualenv.

```
$ source .env/bin/activate
```

If you are a Windows platform, you would activate the virtualenv like this:

```
% .env\Scripts\activate.bat
```

Once the virtualenv is activated, you can install the required dependencies.

```
$ pip install -r requirements.txt
```

At this point you can now synthesize the CloudFormation template for this code.

```
$ cdk synth
```

To add additional dependencies, for example other CDK libraries, just add
them to your `setup.py` file and rerun the `pip install -r requirements.txt`
command.

## Useful commands

 * `cdk ls`          list all stacks in the app
 * `cdk synth`       emits the synthesized CloudFormation template
 * `cdk deploy`      deploy this stack to your default AWS account/region
 * `cdk diff`        compare deployed stack with current state
 * `cdk docs`        open CDK documentation

Enjoy!
