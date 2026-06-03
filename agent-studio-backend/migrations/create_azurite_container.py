"""
Create langfuse container in Azurite for Langfuse blob storage
"""
from azure.storage.blob import BlobServiceClient

# Azurite default connection string
connection_string = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"

try:
    # Create blob service client
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    # Create container
    container_name = "langfuse"
    container_client = blob_service_client.get_container_client(container_name)
    
    if not container_client.exists():
        container_client.create_container()
        print(f"✅ Created container: {container_name}")
    else:
        print(f"ℹ️  Container already exists: {container_name}")
        
except Exception as e:
    print(f"❌ Error: {e}")


