#!/bin/bash
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#365CFF/#A2B9EE/g'
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#16BFD9/#B4E4E6/g'
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#625CEB/#C9C1F1/g'
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#B45BE8/#E2C3F6/g'
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#30BC8A/#B8E3D1/g'
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#00AEE8/#AEDDF0/g'

# Also let's make the background slightly warmer pastel instead of stark white/gray
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#f5f9f9/#FCF9F2/g'
find src -type f -name "*.js" -o -name "*.jsx" | xargs sed -i '' 's/#F3F8FB/#FCF9F2/g'
