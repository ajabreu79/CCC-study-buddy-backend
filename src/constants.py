# ---------------------------------------
# DATABASE COLLECTIONS
# ---------------------------------------
USERS = "users"
MODULES = "modules"
ALLOWED_USERS = "allowed_users"
SESSIONS = "sessions"


# ---------------------------------------
# COMMON FIELD NAMES
# ---------------------------------------
CREATED_BY = "CREATED_BY"
CREATED_AT = "CREATED_AT"
MODIFIED_AT = "modified_at"
MODIFIED_BY = "modified_by"
IS_DELETED = "isDeleted"
PROCESSED_AT = "processed_at"
CHUNK_COUNT = "chunk_count"
ERROR_MESSAGE = "error_message"

# ---------------------------------------
# USER-RELATED FIELDS
# ---------------------------------------
EMAIL = "email"
ACCESS_LEVEL = "access_level"
FIRST_NAME = "first_name"
LAST_NAME = "last_name"
PASSWORD = "password"
USER_ID = "user_id"
HASHED_PW = "hashed_pw"
WORKSPACE_ID = "workspace_id"

# ---------------------------------------
# MODULE-RELATED FIELDS
# ---------------------------------------
AGENT_ID = "agent_id"
NAME = "name"
SYSTEM_PROMPT = "system_prompt"
MODIFIED_AT = "modified_at"
MODIFIED_BY = "modified_by"
STATUS = "status"
VERSION = "version"
PROGRESS = "progress"
STARTED_AT = "started_at"
COMPLETED_AT = "completed_at"
MESSAGES = "messages"
CONTENT = "content"
CHAT_ID = "chat_id"
CRITERIA = "criteria"

# ---------------------------------------
# MODULE RESOURCE-RELATED FIELDS
# ---------------------------------------
MODULE_RESOURCES = "module_resources"
RESOURCE_ID = "resource_id"
ORIGINAL_FILENAME = "original_filename"
S3_KEY = "s3_key"
UPLOAD_TIMESTAMP = "upload_timestamp"
UPLOADER_ID = "uploader_id"
FILE_SIZE = "file_size"
RESOURCE_TYPE = "resource_type"
FILE_URL = "file_url"
PROCESSING_STATUS = "processing_status"
MIME_TYPE = "mime_type"
PDF_TYPE = "pdf"


# ---------------------------------------
# CHAT-RELATED FIELDS
# ---------------------------------------
STARTED_AT = "started_at"
CLOSED_AT = "completed_at"
STATUS = "status"
CURRENT_VERSION = "version"
CHAT = "chat"
VERSION = "version"
MESSAGES = "messages"
WHO = "who"
MESSAGE = "message"
TIMESTAMP = "timestamp"

# ---------------------------------------
# CHAT STATUS TYPES
# ---------------------------------------
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_IN_PROGRESS = "in_progress"
STATUS_REOPENED = "reopened"

# ---------------------------------------
# CHAT MESSAGE SENDER TYPES
# ---------------------------------------
SENDER_AGENT = "agent"
SENDER_USER = "user"

# ---------------------------------------
# ACCESS LEVELS
# ---------------------------------------
ALL = "all"
DELETED = "deleted"
ACTIVE = "active"
ADMIN_LEVEL = 9
MANAGER_LEVEL = 5
USER_LEVEL = 1
DELETED_LEVEL = 0
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
SYSTEM = "system"
ON = "on"
ROLE = "role"


# ---------------------------------------
# TOKEN
# ---------------------------------------
DATA = "data"
MESSAGE = "message"
EXP = "exp"
ALLOWED_USERS = "allowed_users"
TOKEN = "token"
PAGE = "page"
LIMIT = "limit"
TOTAL = "total"

# ---------------------------------------
# GENERAL (ROUTES)
# ---------------------------------------
USER = "user"
MODULE = "module"
CHAT = "chat"


OPENAI_MODEL = "gpt-4o"
