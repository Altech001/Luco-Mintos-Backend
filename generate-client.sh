#!/bin/bash
set -e

# Configuration
BACKEND_URL="http://localhost:8000"
FRONTEND_PROJECT="../mintos"  # Adjust if needed
API_OUTPUT="$FRONTEND_PROJECT/src/lib/api"

echo "🔍 Checking if server is running..."

# Try different possible OpenAPI paths
OPENAPI_PATHS=(
    "$BACKEND_URL/openapi.json"
    "$BACKEND_URL/api/openapi.json"
    "$BACKEND_URL/api/v1/openapi.json"
)

OPENAPI_URL=""
for path in "${OPENAPI_PATHS[@]}"; do
    if curl -s -f "$path" > /dev/null 2>&1; then
        OPENAPI_URL="$path"
        echo "✓ Found OpenAPI schema at: $path"
        break
    fi
done

if [ -z "$OPENAPI_URL" ]; then
    echo "❌ Error: Could not find OpenAPI schema"
    echo "Make sure your backend is running: uvicorn app.main:app --reload"
    exit 1
fi

echo "📥 Downloading OpenAPI schema..."
curl -f -s "$OPENAPI_URL" > openapi.json

# Check file size
file_size=$(wc -c < openapi.json)
if [ "$file_size" -lt 100 ]; then
    echo "❌ Error: Downloaded file is too small ($file_size bytes)"
    cat openapi.json
    exit 1
fi

echo "✓ Downloaded OpenAPI schema ($file_size bytes)"

# Generate to temporary directory
echo "🔧 Generating TypeScript client..."
npx @openapitools/openapi-generator-cli generate \
  -i openapi.json \
  -g typescript-fetch \
  -o ./temp-client \
  --additional-properties=supportsES6=true,withInterfaces=true,typescriptThreePlus=true \
  --global-property=apiTests=false,modelTests=false,apiDocs=false,modelDocs=false

# Create API directory in frontend
echo "📦 Setting up API client in $API_OUTPUT..."
rm -rf "$API_OUTPUT"
mkdir -p "$API_OUTPUT"

# Copy generated files
cp -r ./temp-client/apis "$API_OUTPUT/"
cp -r ./temp-client/models "$API_OUTPUT/"
cp ./temp-client/runtime.ts "$API_OUTPUT/"
cp ./temp-client/index.ts "$API_OUTPUT/"

# Create a configured API client file
cat > "$API_OUTPUT/client.ts" << 'EOF'
import { Configuration, DefaultApi } from './index'

// Get base URL from environment or use default
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Create configuration
const config = new Configuration({
  basePath: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Create and export API client instance
export const apiClient = new DefaultApi(config)

// Helper to set auth token
export function setAuthToken(token: string) {
  config.accessToken = token
}

// Helper to clear auth token
export function clearAuthToken() {
  config.accessToken = undefined
}

// Export configuration for custom instances
export { Configuration }
EOF

# Create README
cat > "$API_OUTPUT/README.md" << 'EOF'
# API Client

Auto-generated API client from OpenAPI schema.

## Regenerate

```bash
cd backend
./generate-client.sh
```

## Usage

```typescript
import { apiClient } from '@/lib/api/client'

// Login example
const response = await apiClient.loginAccessTokenApiV1LoginAccessTokenPost({
  username: 'user@example.com',
  password: 'password'
})

// Set token for authenticated requests
import { setAuthToken } from '@/lib/api/client'
setAuthToken(response.access_token)

// Make authenticated requests
const users = await apiClient.readUsersApiV1UsersGet()
```

## Environment Variables

Add to your `.env` file:

```
VITE_API_URL=http://localhost:8000
```
EOF

# Clean up
rm -rf ./temp-client
rm openapi.json

echo ""
echo "✅ API client generated successfully!"
echo "📁 Location: $API_OUTPUT"
echo ""
echo "📝 Next steps:"
echo ""
echo "1. Add to your .env file:"
echo "   VITE_API_URL=http://localhost:8000"
echo ""
echo "2. Import in your components:"
echo "   import { apiClient } from '@/lib/api/client'"
echo ""
echo "3. Use the API:"
echo "   const users = await apiClient.readUsersApiV1UsersGet()"
echo ""
