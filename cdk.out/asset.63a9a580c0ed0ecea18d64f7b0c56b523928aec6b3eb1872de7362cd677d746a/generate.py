import json
import os
import boto3
import time
import string
import random

ddb = boto3.client('dynamodb')
table = os.environ['TABLE_NAME']
ttl_days = int(os.environ.get('TTL_DAYS', '30'))


def handler(event, context):
    target = json.loads(event['body'])['targetUrl']
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))

    ttl = int(time.time()) + ttl_days * 24 * 60 * 60

    ddb.put_item(
        TableName=table,
        Item={
            'shortCode': {'S': code},
            'longUrl': {'S': target},
            'ttl': {'N': str(ttl)}
        }
    )

    domain = os.environ['DOMAIN']
    return {
        'statusCode': 200,
        'body': json.dumps({'shortUrl': f"{domain}/{code}"})
    }
