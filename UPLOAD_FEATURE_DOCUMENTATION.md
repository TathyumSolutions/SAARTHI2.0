# Unstructured Data Upload Feature - Documentation

## Overview

The Unstructured Data Upload feature allows users to upload various file types (documents, images, videos, audio, emails) with automatic document code generation and file management.

## Features

### 1. **Single Menu Item**
- Unstructured Data is now a single clickable menu item
- Shows all supported types in brackets: "(Docs, Images, Videos, Audio, Emails)"
- No sub-menu expansion required

### 2. **File Type Selection**
Users can select from 5 file type categories:

| Type | Icon | Supported Formats |
|------|------|-------------------|
| Documents | 📄 | .pdf, .docx, .txt, .md, .doc, .rtf, .odt |
| Images | 🖼️ | .jpg, .png, .gif, .svg, .jpeg, .bmp, .webp |
| Videos | 🎥 | .mp4, .avi, .mov, .mkv, .wmv, .flv, .webm |
| Audio | 🎵 | .mp3, .wav, .flac, .m4a, .aac, .ogg, .wma |
| Emails | 📧 | .eml, .msg, .mbox, .pst |

### 3. **Document Code Generation**

Each uploaded file receives a unique document code with the format:

```
TYPE-INITIALS-YYYYMMDD-HHMMSS
```

**Components:**
- **TYPE**: File type prefix (DOC/IMG/VID/AUD/EML)
- **INITIALS**: First 3 letters of filename (uppercase)
- **YYYYMMDD**: Upload date
- **HHMMSS**: Upload time

**Examples:**
```
DOC-SAM-20240122-143052  (sample-doc.pdf uploaded on 2024-01-22 at 14:30:52)
IMG-LOG-20240122-150312  (logo.png uploaded on 2024-01-22 at 15:03:12)
VID-DEM-20240122-161545  (demo-video.mp4 uploaded on 2024-01-22 at 16:15:45)
```

### 4. **Upload Methods**

**Drag & Drop:**
- Drag files directly into the upload area
- Visual feedback with hover effect
- Support for multiple files

**Click to Browse:**
- Click upload area to open file browser
- Select single or multiple files
- Standard OS file picker

### 5. **File Storage**

**Storage Structure:**
```
/uploads/
├── documents/
│   ├── DOC-SAM-20240122-143052.pdf
│   └── DOC-REP-20240122-150000.docx
├── images/
│   ├── IMG-LOG-20240122-150312.png
│   └── IMG-PHO-20240122-160000.jpg
├── videos/
│   ├── VID-DEM-20240122-161545.mp4
│   └── VID-TUT-20240122-170000.mov
├── audio/
│   ├── AUD-SON-20240122-180000.mp3
│   └── AUD-POD-20240122-190000.wav
└── emails/
    ├── EML-MSG-20240122-200000.eml
    └── EML-ARC-20240122-210000.msg
```

**File Naming:**
- Original filename is preserved in metadata
- Physical file is saved as: `{DOCUMENT_CODE}{extension}`
- Example: `DOC-SAM-20240122-143052.pdf`

## API Endpoints

### 1. Upload Files
**POST** `/api/upload/unstructured`

**Request:**
```
Content-Type: multipart/form-data

Form Data:
- files: [file1, file2, ...]  (multiple files)
- file_type: "documents" | "images" | "videos" | "audio" | "emails"
```

**Response:**
```json
{
  "message": "Successfully uploaded 2 file(s)",
  "files": [
    {
      "document_code": "DOC-SAM-20240122-143052",
      "file_name": "sample-document.pdf",
      "saved_filename": "DOC-SAM-20240122-143052.pdf",
      "file_type": "documents",
      "file_size": 2457600,
      "file_path": "/uploads/documents/DOC-SAM-20240122-143052.pdf",
      "upload_date": "2024-01-22 14:30:52",
      "status": "uploaded"
    }
  ],
  "errors": null
}
```

### 2. Get All Uploaded Files
**GET** `/api/upload/files`

**Query Parameters:**
- `file_type` (optional): Filter by type
- `limit` (optional): Limit number of results

**Response:**
```json
{
  "files": [
    {
      "document_code": "DOC-SAM-20240122-143052",
      "file_name": "sample-document.pdf",
      "file_type": "documents",
      "file_size": 2457600,
      "upload_date": "2024-01-22 14:30:52",
      "status": "uploaded"
    }
  ],
  "total": 15
}
```

### 3. Get File by Document Code
**GET** `/api/upload/files/{document_code}`

**Response:**
```json
{
  "file": {
    "document_code": "DOC-SAM-20240122-143052",
    "file_name": "sample-document.pdf",
    "file_type": "documents",
    "file_size": 2457600,
    "file_path": "/uploads/documents/DOC-SAM-20240122-143052.pdf",
    "upload_date": "2024-01-22 14:30:52",
    "status": "uploaded"
  }
}
```

### 4. Delete File
**DELETE** `/api/upload/files/{document_code}`

**Response:**
```json
{
  "message": "File deleted successfully"
}
```

### 5. View File
**GET** `/api/upload/files/view/{document_code}`

Returns the file for viewing in browser (inline).

### 6. Download File
**GET** `/api/upload/files/download/{document_code}`

Downloads the file (as attachment).

### 7. Get Supported File Types
**GET** `/api/upload/types`

**Response:**
```json
{
  "file_types": {
    "documents": {
      "label": "Documents",
      "icon": "📄",
      "extensions": ["pdf", "docx", "txt", "md"]
    },
    "images": {
      "label": "Images",
      "icon": "🖼️",
      "extensions": ["jpg", "png", "gif", "svg"]
    }
  }
}
```

## User Interface

### Upload Page Layout

```
┌─────────────────────────────────────────────┐
│  Unstructured Data Upload                   │
│  Upload documents, images, videos, audio... │
├─────────────────────────────────────────────┤
│                                             │
│  Select File Type:                          │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐      │
│  │  📄  │ │  🖼️  │ │  🎥  │ │  🎵  │      │
│  │ Docs │ │Images│ │Videos│ │Audio │      │
│  └──────┘ └──────┘ └──────┘ └──────┘      │
│                                             │
│  Upload Files:                              │
│  ┌─────────────────────────────────────┐   │
│  │           📤                        │   │
│  │   Drag & drop files here           │   │
│  │   or click to browse               │   │
│  │   Maximum file size: 100MB         │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  [Clear Selection]  [Upload Files]          │
│                                             │
│  Uploaded Files:                            │
│  ┌─────────────────────────────────────┐   │
│  │ Code        | Name      | Type      │   │
│  ├─────────────────────────────────────┤   │
│  │ DOC-...     | file.pdf  | 📄 Doc   │   │
│  │ IMG-...     | pic.jpg   | 🖼️ Img   │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Features

1. **File Type Selection Cards**
   - Visual cards with icons
   - Click to select type
   - Shows supported formats
   - Selected card is highlighted

2. **Upload Area**
   - Large drag & drop zone
   - Click to open file browser
   - Visual feedback on hover/drag
   - Progress bar during upload

3. **Uploaded Files Table**
   - Shows all uploaded files
   - Displays document codes
   - File metadata (name, type, size, date)
   - Action buttons (View, Delete)

4. **Alert Messages**
   - Success messages (green)
   - Error messages (red)
   - Auto-dismiss after 5 seconds

## Usage Examples

### JavaScript - Upload Files

```javascript
async function uploadFiles(files, fileType) {
    const formData = new FormData();
    
    files.forEach(file => {
        formData.append('files', file);
    });
    formData.append('file_type', fileType);
    
    const response = await fetch('/api/upload/unstructured', {
        method: 'POST',
        body: formData,
        headers: {
            'Authorization': 'Bearer ' + token
        }
    });
    
    const data = await response.json();
    console.log('Uploaded:', data.files);
}
```

### Python - Upload Files

```python
import requests

files = [
    ('files', open('document.pdf', 'rb')),
    ('files', open('image.jpg', 'rb'))
]

data = {'file_type': 'documents'}

response = requests.post(
    'http://localhost:5000/api/upload/unstructured',
    files=files,
    data=data,
    headers={'Authorization': 'Bearer your-token'}
)

print(response.json())
```

### cURL - Upload File

```bash
curl -X POST http://localhost:5000/api/upload/unstructured \
  -H "Authorization: Bearer your-token" \
  -F "files=@document.pdf" \
  -F "files=@image.jpg" \
  -F "file_type=documents"
```

## Configuration

### Upload Settings

In `app/api/routes/upload_routes.py`:

```python
# Upload folder location
UPLOAD_FOLDER = '/home/claude/saarthi_enterprise_api/uploads'

# Maximum file size (100MB)
MAX_FILE_SIZE = 100 * 1024 * 1024

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    'documents': {'pdf', 'docx', 'doc', 'txt', 'md'},
    'images': {'jpg', 'jpeg', 'png', 'gif', 'svg'},
    'videos': {'mp4', 'avi', 'mov', 'mkv'},
    'audio': {'mp3', 'wav', 'flac', 'm4a'},
    'emails': {'eml', 'msg', 'mbox'}
}
```

## Testing

### Test Upload

1. Start the Flask server:
```bash
python run.py
```

2. Open browser:
```
http://localhost:5000/unstructured-data
```

3. Select file type (e.g., Documents)

4. Upload a file:
   - Drag & drop OR click to browse
   - Select file(s)
   - Click "Upload Files"

5. Check result:
   - Document code is generated
   - File appears in table
   - File is saved to `/uploads/documents/`

### Test with Postman

1. Create POST request to `/api/upload/unstructured`
2. Set body to `form-data`
3. Add key `files` (type: file) with your files
4. Add key `file_type` (type: text) with value `documents`
5. Send request
6. Check response for document codes

## Error Handling

### Common Errors

**No files provided:**
```json
{
  "error": "No files provided"
}
```

**Invalid file type:**
```json
{
  "error": "Invalid or missing file type"
}
```

**File not found:**
```json
{
  "error": "File not found"
}
```

**Wrong file format:**
```json
{
  "message": "Successfully uploaded 1 file(s)",
  "files": [...],
  "errors": ["wrongfile.exe: Invalid file type for documents"]
}
```

## Production Considerations

### Current Implementation (Development)
- Files stored in local filesystem
- Metadata stored in memory (Python list)
- No authentication required

### Production Requirements

1. **Database Storage**
   - Replace in-memory list with database (PostgreSQL)
   - Add file metadata table
   - Track user ownership

2. **Authentication**
   - Add JWT token verification
   - User-specific file access
   - Role-based permissions

3. **Cloud Storage**
   - Consider AWS S3, Google Cloud Storage, or Azure Blob
   - Better scalability and reliability
   - CDN for faster access

4. **File Validation**
   - Virus scanning
   - Content validation
   - Size limits per user/plan

5. **Backup & Recovery**
   - Regular backups
   - Disaster recovery plan
   - File versioning

## Next Steps

1. ✅ Basic upload functionality implemented
2. ✅ Document code generation working
3. ✅ File type categorization
4. ✅ View and delete operations

**To Implement:**
- [ ] Database integration for metadata
- [ ] User authentication and authorization
- [ ] File preview functionality
- [ ] Search and filter capabilities
- [ ] Bulk operations (delete multiple)
- [ ] File versioning
- [ ] Cloud storage integration
- [ ] RAG processing pipeline
