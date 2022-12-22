#
# Setup IOA in the master account
#
import json
import logging
import os
import boto3
import requests

cloudformation_client = boto3.client('cloudformation')

CLOUDTRAIL_NAME = 'cs-horizon-org-trail'
RETRIES = 12
SLEEP = 10

logger = logging.getLogger()
logger.setLevel(logging.INFO)

admin_role_arn = os.environ['AdministrationRoleARN']
exec_role_arn = os.environ['ExecutionRoleARN']
aws_region = os.environ['AWSRegion']
account_id = os.environ['AWSAccount']

def create_cloudtrail(s3_bucket_name, region):
    client_ct = boto3.client('cloudtrail', region_name=region)
    logger.info('**** Creating additional org wide trail {} '.format(CLOUDTRAIL_NAME))
    try:
        client_ct.create_trail(
            Name=CLOUDTRAIL_NAME,
            S3BucketName=s3_bucket_name,
            IsMultiRegionTrail=True,
            IsOrganizationTrail=True,
        )
        client_ct.start_logging(Name=CLOUDTRAIL_NAME)
        return True
    except Exception as error:
        logger.info('Exception creating trail {}'.format(error))
        return False


def delete_cloudtrail(region):
    client_ct = boto3.client('cloudtrail', region_name=region)
    logger.info('**** Deleting org wide trail {} ****'.format(CLOUDTRAIL_NAME))
    try:
        client_ct.stop_logging(Name=CLOUDTRAIL_NAME)
        client_ct.delete_trail(
            Name=CLOUDTRAIL_NAME)
        return True
    except Exception as error:
        logger.info('**** Exception deleting trail {} **** '.format(error))
        return False


def cfnresponse_send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
    responseUrl = event['ResponseURL']
    responseBody = {'Status': responseStatus,
                    'Reason': 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
                    'PhysicalResourceId': physicalResourceId or context.log_stream_name, 'StackId': event['StackId'],
                    'RequestId': event['RequestId'], 'LogicalResourceId': event['LogicalResourceId'], 'NoEcho': noEcho,
                    'Data': responseData}

    json_responseBody = json.dumps(responseBody)
    logger.info('**** Registration Response {} **** '.format(json_responseBody))
    headers = {
        'content-type': '',
        'content-length': str(len(json_responseBody))
    }

    try:
        response = requests.put(responseUrl,
                                data=json_responseBody,
                                headers=headers)
        print("Status code: " + response.reason)
    except Exception as error:
        logger.info('**** Failed to exectute registration with error {} **** '.format(error))


def trail_exists():
    #
    # Check if we have an existing trail
    #
    ct_client = boto3.client('cloudtrail')
    # Check that we have some trails
    trail_list = ct_client.list_trails()['Trails']
    # Check that we have some trails
    if len(trail_list) > 0:
        for trail in trail_list:
            if trail['Name'] == CLOUDTRAIL_NAME:
                logger.info('**** CloudTrail {} exists already ****'.format(CLOUDTRAIL_NAME))
                return True
            else:
                logger.info('**** CloudTrail {} does not exist ****'.format(CLOUDTRAIL_NAME))
    return False


def lambda_handler(event, context):
    #
    # First check that we have all the data required
    #
    try:
        logger.info('Got event {}'.format(event))
        logger.info('Context {}'.format(context))
        #
        # Extract the values required to create the stacks
        #
        iam_stack_url = event['ResourceProperties']['IAMStackURL']
        iam_stack_name = event['ResourceProperties']['IAMStackName']
        logger.info('EVENT Received: {}'.format(event))
        keys = event['ResourceProperties'].keys()
        iam_stackset_param_list = []
        #
        # Build param list from event ResourceProperties
        # IAMStackSetURL, IAMStackSetName and ServiceToken are not input params
        #
        exclude_params_list = (
            'IAMStackURL', 'IAMStackName', 'ServiceToken')
        for key in keys:
            keyDict = {}
            if key in exclude_params_list:
                pass
            else:
                keyDict['ParameterKey'] = key
                keyDict['ParameterValue'] = event['ResourceProperties'][key]
                iam_stackset_param_list.append(dict(keyDict))
    except Exception as error:
        logger.error(error)
        response_data = {"Status": str(error)}
        status = 'FAILED'
        cfnresponse_send(event, context, status, response_data, "CustomResourcePhysicalID")

    #
    # Proceed with building stack
    try:
        response_data = {}
        clist = ['CAPABILITY_NAMED_IAM']
        if event['RequestType'] in ['Create']:
            #
            # Creating stackinstance if IOA enabled.
            #
            if ioa_enabled == 'true':
                desc = 'Create EventBridge rule in child accounts in every region to send CloudTrail events to CrowdStrike'

                stack_op_result = cloudformation_client.create_stack(
                        StackName=iam_stack_name,
                        TemplateURL=iam_stack_url,
                        Parameters=iam_stackset_param_list,
                        TimeoutInMinutes=5,
                        Capabilities=['CAPABILITY_NAMED_IAM']
                    )
                if stack_op_result['ResponseMetadata']['HTTPStatusCode'] == 200:
                    logger.info('**** Created StackSet {} ****'.format(iam_stack_name))
                else:
                    logger.info('**** Failed to create StackSet {} ****'.format(iam_stack_name))
                #
                # Create org wide trail if required.
                # When set to false we will create a new trail and send events to CrowdStike
                #
                if use_existing_cloudtrail == 'false' and trail_exists() == False:
                    cloudtrail_result = create_cloudtrail(ct_bucket, aws_region)
                else:
                    # Don't create org wide trail as customer selected true
                    # Set the result to True and continue
                    cloudtrail_result = True
                if stack_op_result and cloudtrail_result:
                    status = 'SUCCESS'
                else:
                    logger.info('Failed to apply stackset {}'.format(iam_stack_name))
                    status = 'FAILED'


        elif event['RequestType'] in ['Update']:
            logger.info('Event = ' + event['RequestType'])
            if ioa_enabled == 'true' and use_existing_cloudtrail == 'false' and trail_exists() == False:

                cloudtrail_result = create_cloudtrail(ct_bucket, aws_region)
                logger.info('cloudtrail_result: {}'.format(cloudtrail_result))
            elif ioa_enabled == 'true' and use_existing_cloudtrail == 'true' and trail_exists() == True:
                delete_cloudtrail(aws_region)
            if trail_exists():
                    delete_cloudtrail(aws_region)

            status = 'SUCCESS'
            return

        elif event['RequestType'] in ['Delete']:
            logger.info('Event = ' + event['RequestType'])
            cloudformation_client.delete_stack(StackName=iam_stack_name)
            if trail_exists() == True:
                delete_cloudtrail(aws_region)
            else:
                logger.info('**** CloudTrail {} does not exist - Skipping deletion ****'.format(CLOUDTRAIL_NAME))

                pass
            # Send valid response during stack deletion.
            # Sending failure would only cause stack deletion problems
            status = 'SUCCESS'
    except Exception as error:
        logger.info('Error performing {} on Stack {}'.format(event['RequestType'],iam_stack_name))
        response_data = {"Status": str(error)}
        status = 'FAILED'
        return
    finally:
        cfnresponse_send(event, context, status, response_data, "CustomResourcePhysicalID")
