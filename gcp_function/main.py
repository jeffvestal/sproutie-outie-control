import os
import functions_framework
from google.cloud import storage

@functions_framework.http
def upload_snapshot(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    # 1. Auth Check
    auth_header = request.headers.get('Authorization')
    expected_token = os.environ.get('AUTH_TOKEN')
    
    if not auth_header or auth_header != f"Bearer {expected_token}":
        return 'Unauthorized', 401

    # 2. Get Bucket Name
    bucket_name = os.environ.get('BUCKET_NAME')
    if not bucket_name:
        return 'Bucket name not configured', 500

    # 3. Check for File in Request
    if 'file' not in request.files:
        return 'No file part in the request', 400
    
    file = request.files['file']
    if file.filename == '':
        return 'No selected file', 400

    # 4. Upload to GCS
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file.filename)
        
        blob.upload_from_file(file)
        
        return f'File {file.filename} uploaded to {bucket_name}.', 200
    except Exception as e:
        print(f"Error uploading file: {e}")
        return f'Error uploading file: {str(e)}', 500
