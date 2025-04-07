# RAG Implementation Plan for Eaton Call Center Backend

## 1. Amazon S3 Bucket Setup

### 1.1. Create S3 Bucket

- Create a new S3 bucket in the AWS Console
- Configure appropriate permissions (CORS settings to allow uploads from your application)
- Create IAM user with programmatic access and S3 permissions
- Note the bucket name, region, access key, and secret key

### 1.2. Environment Variables

- Update `.env` file to include:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_BUCKET_NAME`
  - `AWS_REGION`

## 2. Backend Changes

### 2.1. Install Required Libraries

- Add to `requirements.txt`:
  - `boto3`
  - `python-multipart`

### 2.2. Create S3 Handler Service

- Create new file: `src/services/S3Handler.py`
- Implement functions for:
  - Uploading files to S3
  - Generating presigned URLs
  - Listing files in a directory
  - Deleting files

### 2.3. Update Module API Endpoints

- Modify `src/routes/module.py`:
  - Add new endpoint `/upload-pdf/{agent_id}` for PDF upload
  - Add PDF metadata storage in Firestore
  - Update module schema to track associated PDFs
  - Implement PDF deletion when a module is deleted

### 2.4. Create PDF Processing Service

- Create new file: `src/services/PDFProcessor.py`
- Implement functions for:
  - Validating PDF files
  - Extracting text content
  - Parsing structure
  - Preparing data for embedding

### 2.5. RAG Implementation

- Update `src/services/EmbeddingHandler.py`:

  - Modify to handle PDF files from S3
  - Implement chunking of PDF documents
  - Create method to update existing embeddings when PDFs change

- Update `src/services/LangChainHelper.py`:
  - Enhance RAG prompt templates to reference module-specific documents
  - Add metadata filtering to retrievers based on agent_id

### 2.6. Modify Chat API

- Update `src/routes/chat.py`:
  - Enhance the chat API to use RAG when answering questions
  - Implement source tracking and citation
  - Create endpoint to retrieve source documents

## 3. Integration Points

### 3.1. Module Creation/Edit Flow

- In `src/routes/module.py`:
  - Update the module creation endpoint to handle PDF attachments
  - Implement a transaction to ensure both the module and its PDFs are created/updated consistently
  - Add validation to ensure only managers and admins can upload PDFs

### 3.2. PDF to RAG Pipeline

1. When a PDF is uploaded to S3:

   - Create a record in Firestore with metadata
   - Process the PDF to extract text
   - Create chunks for embedding
   - Generate embeddings using the existing `EmbeddingHandler`
   - Store embeddings in Pinecone with metadata including:
     - `agent_id` (module ID)
     - `file_id`
     - `chunk_id`
     - `page_number`

2. When a chat request is received:
   - Filter Pinecone vectors by the relevant `agent_id`
   - Use similarity search to find relevant chunks
   - Incorporate chunks into the prompt for the LLM
   - Include source citations in the response

## 4. Detailed Implementation Tasks

### 4.1. S3Handler.py Implementation

Create a new file `src/services/S3Handler.py`:

- Implement connection to S3 using boto3
- Create functions:
  - `upload_file(local_file_path, s3_key, metadata=None)`
  - `generate_presigned_url(s3_key, expiration=3600)`
  - `delete_file(s3_key)`
  - `list_files(prefix)`
- Add helper methods for file type validation

### 4.2. Module Schema and API Updates

Update the Firebase schema for modules to include PDF references:

- Add a new collection or subcollection for module resources
- Store metadata:
  - File ID
  - Original filename
  - S3 key
  - Upload timestamp
  - Uploader ID
  - File size
  - Status (processed, processing, error)

Add new endpoints to `src/routes/module.py`:

- POST /module/{agent_id}/upload-pdf - Upload a PDF for a module
- GET /module/{agent_id}/resources - List all resources for a module
- DELETE /module/{agent_id}/resource/{resource_id} - Delete a specific resource

### 4.3. PDF Processing and Embedding

Create a new file `src/services/PDFProcessor.py` with methods:

- `extract_text_from_pdf(file_path)`
- `chunk_text(text, chunk_size=1000, overlap=200)`
- `process_pdf_for_embedding(file_path, metadata)`

Enhance `src/services/EmbeddingHandler.py`:

- Add function `process_s3_pdf(s3_key, metadata)`
- Update `embed_file()` to support PDF processing from S3
- Add method for re-embedding when a document changes
- Implement transactions to ensure consistency between Firestore and Pinecone

### 4.4. RAG Query Integration

Update `src/services/LangChainHelper.py`:

- Enhance `chat_stream_with_retrieve()` function:
  - Add metadata filtering by `agent_id`
  - Improve prompt templates with document context
  - Add citation handling
- Add configuration for different retrieval strategies:
  - Parent-child retrieval
  - Context retrieval
  - Hybrid search

### 4.5. Frontend Integration Notes

The frontend will need to:

- Add file upload UI to module creation/edit forms
- Display resource list for each module
- Allow deletion of resources
- Show processing status of uploaded files
- Display source citations in chat responses

## 5. Security Considerations

- Ensure S3 bucket has proper CORS configuration
- Implement file type validation
- Limit file size (suggest 10MB max)
- Set up proper IAM permissions for S3
- Add authentication checks to all new endpoints
- Sanitize user inputs and filenames
- Validate PDF content before processing
