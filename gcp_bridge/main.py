import os
import functions_framework
from google.cloud import storage

# Initialize the GCS client
storage_client = storage.Client()

@functions_framework.http
def upload_file(request):
    """HTTP Cloud Function to upload a file to GCS.
    Args:
        request (flask.Request): The request object.
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`.
    """
    # 1. Auth Validation
    auth_header = request.headers.get('Authorization')
    expected_token = os.environ.get('AUTH_TOKEN')
    
    if not expected_token:
        return 'Function configuration error: AUTH_TOKEN not set.', 500

    if not auth_header or auth_header != f'Bearer {expected_token}':
        return 'Unauthorized', 401

    # 2. File Retrieval
    if 'file' not in request.files:
        return 'No file part in the request', 400
    
    file = request.files['file']
    if file.filename == '':
        return 'No selected file', 400

    # 3. GCS Upload
    bucket_name = os.environ.get('BUCKET_NAME')
    if not bucket_name:
        return 'Function configuration error: BUCKET_NAME not set.', 500

    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file.filename)
        blob.upload_from_file(file.stream, content_type=file.content_type)
        return f'File {file.filename} uploaded to bucket {bucket_name}.', 200
    except Exception as e:
        return f'Error uploading file: {str(e)}', 500
