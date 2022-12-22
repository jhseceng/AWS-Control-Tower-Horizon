import logging

import boto3
import os

#
# This lambda is triggered by the "CreateManagedAccount" cloudtrail event.
# The lambda will create a new stack instance from the stackset defined by the
# ENV variable StackSetName
#
StackSetName = os.environ['StackSetName']

logger = logging.getLogger()
logger.setLevel(logging.INFO)
stackset_list = [StackSetName]
result = {"ResponseMetadata": {"HTTPStatusCode": "400"}}

def lambda_handler(event, context):
    masterAcct = event['account']
    eventDetails = event['detail']
    regionName = eventDetails['awsRegion']
    eventName = eventDetails['eventName']
    srvEventDetails = eventDetails['serviceEventDetails']
    if eventName == 'CreateManagedAccount':
        newAccInfo = srvEventDetails['createManagedAccountStatus']
        cmdStatus = newAccInfo['state']
        if cmdStatus == 'SUCCEEDED':
            '''Sucessful event recieved'''
            accId = newAccInfo['account']['accountId']
            CFT = boto3.client('cloudformation')
            for item in stackset_list:
                try:
                    CFT.create_stack_instances(
                        StackSetName=item,
                        Accounts=[accId],
                        Regions=[regionName],
                        OperationPreferences={
                            "FailureToleranceCount": 0,
                            "MaxConcurrentCount": 3,
                        })
                    logger.info('Processed {} Sucessfully'.format(item))

                except Exception as e:
                    logger.error('Unable to launch in:{}, REASON: {}'.format(item, e))
        else:
            '''Unsucessful event recieved'''
            logger.info('Unsucessful Event Recieved. SKIPPING :{}'.format(event))
            return (False)
    else:
        logger.info('Control Tower Event Captured :{}'.format(event))
