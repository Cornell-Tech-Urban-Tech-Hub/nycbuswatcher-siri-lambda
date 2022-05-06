import boto3


aws_bucket_name="busobservatory"
aws_region_name="us-east-1"
aws_secret_name="lambda_developer_keys"
aws_access_key_id = "AKIA4VPE6LPCCRMQEX7G"
aws_secret_access_key = "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"
    

session = boto3.Session(
    region_name=aws_region_name,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key)
s3 = session.resource('s3')
result = s3.Bucket(aws_bucket_name).upload_file('s3test.py','tmp/s3test.py')