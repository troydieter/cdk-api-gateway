import os, boto3
ddb = boto3.client('dynamodb')
table = os.environ['TABLE_NAME']

def handler(event, context):
    code = event['pathParameters']['code']
    resp = ddb.get_item(TableName=table, Key={'shortCode': {'S': code}})
    if 'Item' in resp:
        return {'statusCode': 301, 'headers': {'Location': resp['Item']['longUrl']['S']}}
    else:
        return {'statusCode': 404, 'body': f"No redirect found for {code}"}
