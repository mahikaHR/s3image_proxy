import boto3
import os
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import requests
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

security = HTTPBearer()
API_TOKEN = os.getenv("API_TOKEN")

MCLEOD_BASE_URL = os.getenv("MCLEOD_BASE_URL", "https://tms-syfn.loadtracking.com/ws")
MCLEOD_COMPANY_ID = os.getenv("MCLEOD_COMPANY_ID")
MCLEOD_API_KEY = os.getenv("MCLEOD_API_KEY")

ROW_TYPE = "o"  #hardcoded values 
DOCUMENT_TYPE_ID = "3"  #hardcoded values 

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("AWS_SECRET_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )

def upload_to_mcleod(order_id: str, file_content: bytes, file_name: str):
    url = f"{MCLEOD_BASE_URL}/images/{ROW_TYPE}/{order_id}/{DOCUMENT_TYPE_ID}"
    
    headers = {
        "X-com.mcleodsoftware.CompanyID": MCLEOD_COMPANY_ID,
        "Content-Type": "image/jpeg",
        "Content-Disposition": f'file; filename="{file_name}"; documentid={file_name}; fileExtension="jpg"'
    }

    if MCLEOD_API_KEY:
        headers["Authorization"] = f"Bearer {MCLEOD_API_KEY}"

    response = requests.post(
        url,
        headers=headers,
        data=file_content,  # Send bytes
        timeout=60
    )

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"McLeod API error: {response.text}"
        )

    return response.json() if response.text else {"status": "success"}

@app.post("/upload-image/")
async def upload_image(
    s3_file_name: str,
    order_id: str,
    token: str = Depends(verify_token)
):
    """
    Fetch a JPEG image from S3 and upload it to McLeod.
    Uses McLeod's /images/o/{order_id}/3 endpoint.
    
    Args:
        s3_file_name: Name of the JPEG image file in S3
        order_id: McLeod order ID
    """
    try:
        s3_client = get_s3_client()
        bucket = os.getenv("AWS_S3_BUCKET")

        # Get the object from s3 using file name
        response = s3_client.get_object(Bucket=bucket, Key=s3_file_name)
        
        # Verify content type
        content_type = response.get('ContentType', '')
        if not content_type.startswith('image/jpeg'):
            raise HTTPException(
                status_code=400,
                detail=f"File must be a JPEG image. Got content type: {content_type}"
            )

        file_content = response['Body'].read()

        result = upload_to_mcleod(
            order_id=order_id,
            file_content=file_content,
            file_name=s3_file_name
        )

        return {
            "status": "success",
            "message": "File successfully uploaded to McLeod",
            "s3_file": s3_file_name,
            "order_id": order_id,
            "mcleod_response": result
        }

    except boto3.exceptions.ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        if error_code == 'NoSuchKey':
            raise HTTPException(
                status_code=404,
                detail=f"File {s3_file_name} not found in S3 bucket"
            )
        raise HTTPException(
            status_code=500,
            detail=f"S3 error: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port) 