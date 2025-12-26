# Debug Guide

## What Was Added

1. **Error Boundary** - Catches React errors and displays them
2. **Console Logging** - Logs in main.tsx and App.tsx to track rendering
3. **CSS Indicator** - Green 4px dot in top-left corner when CSS loads
4. **Root Element Check** - Verifies root element exists before mounting

## How to Debug

### 1. Check Browser Console
Open DevTools (F12) and look for:
- `[main.tsx] Root element found, mounting React...`
- `[main.tsx] React mounted successfully`
- `[App] Rendering, view: dashboard, selectedAgentId: null`

### 2. Check Visual Indicators
- **Green dot** (top-left): CSS is loading
- **Dark background**: Tailwind is working
- **Sidebar visible**: AppShell is rendering

### 3. Check for Errors
If you see an error screen:
- Copy the error message
- Check the browser console for full stack trace
- Verify API is running on port 3001

### 4. Common Issues

**Blank white screen:**
- Check console for JavaScript errors
- Verify `index.html` has `<div id="root"></div>`
- Check if CSS is loading (green dot should appear)

**API errors:**
- Ensure API server is running: `pnpm -C apps/api dev`
- Check proxy in `vite.config.ts` points to `http://localhost:3001`

**Tailwind not working:**
- Verify `postcss.config.js` exists
- Check `tailwind.config.js` content paths
- Ensure `index.css` has `@tailwind` directives

## Quick Test

1. Start dev server: `pnpm -C apps/web dev`
2. Open http://localhost:3000
3. Open DevTools console (F12)
4. Look for debug messages
5. Check for green dot (CSS indicator)

