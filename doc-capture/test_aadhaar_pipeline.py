import sys
import os
import argparse
import asyncio
import uuid
import grpc

# Add the current directory and the shared directory to the path so generated files and log_utils load correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, '..', 'shared'))

from generated import doc_capture_pb2 as pb2
from generated import doc_capture_pb2_grpc as pb2_grpc

async def main():
    parser = argparse.ArgumentParser(description="Test full Aadhaar capture pipeline via gRPC")
    parser.add_argument("-p1", "--part1", required=True, help="Path to Aadhaar front image")
    parser.add_argument("-p2", "--part2", required=True, help="Path to Aadhaar back image")
    parser.add_argument("--lang", default="hi", choices=["hi", "en"], help="Language code (default: hi)")
    parser.add_argument("--host", default="localhost:50058", help="gRPC host address (default: localhost:50058)")
    
    args = parser.parse_args()
    
    p1_path = args.part1
    p2_path = args.part2
    lang = args.lang
    host = args.host
    
    # Check if files exist
    if not os.path.exists(p1_path):
        print(f"❌ Error: Part 1 file not found at {p1_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(p2_path):
        print(f"❌ Error: Part 2 file not found at {p2_path}", file=sys.stderr)
        sys.exit(1)
        
    session_id = str(uuid.uuid4())
    print(f"🚀 Starting Aadhaar test capture session...")
    print(f"   Session ID: {session_id}")
    print(f"   Language:   {lang}")
    print(f"   Host:       {host}")
    print("-" * 60)
    
    channel_options = [
        ("grpc.max_send_message_length", 100 * 1024 * 1024),
        ("grpc.max_receive_message_length", 100 * 1024 * 1024),
    ]
    
    async with grpc.aio.insecure_channel(host, options=channel_options) as channel:
        stub = pb2_grpc.DocumentCaptureStub(channel)
        
        # 1. Start Session
        print("➡️  [STEP 1] Initializing session...")
        try:
            start_req = pb2.StartCaptureRequest(
                session_id=session_id,
                scheme_id="scheme_micro_business_001",
                language=lang
            )
            session_res = await stub.StartSession(start_req, timeout=10.0)
            if not session_res.success:
                print(f"❌ Failed to start session: {session_res.error}")
                sys.exit(1)
                
            print("✅ Session started successfully!")
            print(f"   Document ID: {session_res.current_document_id}")
            print(f"   Page ID:     {session_res.current_page_id}")
            print(f"   Total Pages: {session_res.total_pages}")
            print("-" * 60)
        except Exception as e:
            print(f"❌ gRPC connection error: {e}")
            print("Make sure the doc-capture service is running!")
            sys.exit(1)
            
        # Helper function to read image bytes
        def get_image_bytes(path):
            with open(path, "rb") as f:
                return f.read()
                
        # 2. Process Part 1 (Front)
        print("➡️  [STEP 2] Processing Part 1 (Front)...")
        print(f"   Uploading: {p1_path}")
        p1_bytes = get_image_bytes(p1_path)
        
        p1_req = pb2.ProcessDocRequest(
            session_id=session_id,
            document_id="doc_aadhaar_002",
            page_id="front",
            image_data=p1_bytes,
            content_type="image/jpeg",
            filename=os.path.basename(p1_path)
        )
        
        p1_res = await stub.ProcessDocument(p1_req, timeout=60.0)
        if not p1_res.success:
            print(f"❌ Part 1 validation failed!")
            print(f"   Error Key:  {p1_res.validation_error_key}")
            print(f"   Error Text: {p1_res.validation_error_text}")
            print(f"   Field ID:   {p1_res.validation_field_id}")
            sys.exit(1)
            
        print("✅ Part 1 processed successfully!")
        print(f"   Page Complete:     {p1_res.page_complete}")
        print(f"   Document Complete: {p1_res.document_complete}")
        print(f"   Next Page ID:      {p1_res.next_page_id}")
        print("-" * 60)
        
        # 3. Process Part 2 (Back)
        print("➡️  [STEP 3] Processing Part 2 (Back)...")
        print(f"   Uploading: {p2_path}")
        p2_bytes = get_image_bytes(p2_path)
        
        p2_req = pb2.ProcessDocRequest(
            session_id=session_id,
            document_id="doc_aadhaar_002",
            page_id="back",
            image_data=p2_bytes,
            content_type="image/jpeg",
            filename=os.path.basename(p2_path)
        )
        
        p2_res = await stub.ProcessDocument(p2_req, timeout=60.0)
        if not p2_res.success:
            print(f"❌ Part 2 validation failed!")
            print(f"   Error Key:  {p2_res.validation_error_key}")
            print(f"   Error Text: {p2_res.validation_error_text}")
            print(f"   Field ID:   {p2_res.validation_field_id}")
            sys.exit(1)
            
        print("✅ Part 2 processed successfully!")
        print(f"   Page Complete:     {p2_res.page_complete}")
        print(f"   Document Complete: {p2_res.document_complete}")
        print(f"   All Complete:      {p2_res.all_complete}")
        print("-" * 60)
        
        # 4. Show Extracted Results
        print("🎉 [RESULT] Aadhaar Extraction Success!")
        print(f"   Extracted Fields JSON:\n{p2_res.extracted_fields_json}")
        if p2_res.confirm_fields:
            print(f"   Fields requiring confirmation: {list(p2_res.confirm_fields)}")
        else:
            print(f"   Fields requiring confirmation: None")
            
if __name__ == "__main__":
    asyncio.run(main())
