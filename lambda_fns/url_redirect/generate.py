import json
import os
import boto3
import string, random

ddb = boto3.client('dynamodb')
table = os.environ['TABLE_NAME']

def handler(event, context):
    target = json.loads(event['body'])['targetUrl']
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    ddb.put_item(TableName=table, Item={'shortCode': {'S': code}, 'longUrl': {'S': target}})
    domain = os.environ['DOMAIN']
    return {'statusCode': 200, 'body': json.dumps({'shortUrl': f"{domain}/{code}"})}
