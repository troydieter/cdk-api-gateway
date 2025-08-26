import json
import logging
import os
from typing import Dict, Any, List

# Configure logging
logger = logging.getLogger()
log_level = os.environ.get("LOG_LEVEL", "INFO")
logger.setLevel(log_level)

# Optional: Import AWS Lambda Powertools if available
try:
    from aws_lambda_powertools import Logger, Metrics, Tracer
    from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType
    from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
    from aws_lambda_powertools.utilities.typing import LambdaContext
    
    # Initialize Powertools
    logger = Logger(service=os.environ.get("POWERTOOLS_SERVICE_NAME", "created-status-processor"))
    metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "ApiGatewayFanOut"))
    tracer = Tracer()
    
    # Initialize batch processor
    processor = BatchProcessor(event_type=EventType.SQS)
    
    # Define record handler
    @tracer.capture_method
    def record_handler(record: SQSRecord) -> Dict[str, Any]:
        """Process an individual SQS record"""
        try:
            payload = record.body
            logger.info(f"Processing message with created status: {payload}")
            
            # Parse the message body if it's JSON
            try:
                message_body = json.loads(payload)
                logger.info(f"Message content: {message_body}")
                
                # Add your business logic here
                # For example, store in database, trigger another process, etc.
                
                # Record custom metrics
                metrics.add_metric(name="ProcessedMessages", unit="Count", value=1)
                
                return {"status": "success", "message": "Message processed successfully"}
            except json.JSONDecodeError:
                logger.warning(f"Message is not valid JSON: {payload}")
                # Still process as text if not JSON
                # Add your text processing logic here
                
                return {"status": "success", "message": "Non-JSON message processed"}
        except Exception as e:
            logger.error(f"Error processing record: {str(e)}", exc_info=True)
            # By raising the exception, the record will be sent to the DLQ after max retries
            raise
    
    @logger.inject_lambda_context(log_event=True)
    @metrics.log_metrics(capture_cold_start_metric=True)
    @tracer.capture_lambda_handler
    def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
        """Lambda handler for processing SQS messages with 'created' status"""
        # Process the batch of records
        return processor.process(event=event, record_handler=record_handler)

except ImportError:
    # Fallback if Powertools is not available
    def handler(event: Dict[str, Any], context: Any) -> None:
        """Simple Lambda handler for processing SQS messages with 'created' status"""
        logger.info("Request: " + json.dumps(event))
        
        try:
            records = event.get("Records", [])
            
            for record in records:
                try:
                    payload = record.get("body", "{}")
                    logger.info(f"Received message with created status: {payload}")
                    
                    # Parse the message body if it's JSON
                    try:
                        message_body = json.loads(payload)
                        logger.info(f"Message content: {message_body}")
                        
                        # Add your business logic here
                        # For example, store in database, trigger another process, etc.
                        
                    except json.JSONDecodeError:
                        logger.warning(f"Message is not valid JSON: {payload}")
                        # Still process as text if not JSON
                        # Add your text processing logic here
                        
                except Exception as record_error:
                    logger.error(f"Error processing record: {str(record_error)}", exc_info=True)
                    # Continue processing other records
                    continue
                    
            return {"statusCode": 200, "body": json.dumps({"message": "Batch processed successfully"})}
            
        except Exception as e:
            logger.error(f"Error processing batch: {str(e)}", exc_info=True)
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}