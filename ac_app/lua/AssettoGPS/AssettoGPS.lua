-- Assetto GPS Companion (CSP Lua App)
-- Auto-boots server, displays Phone Pairing URL, and syncs headlights

local server_dir = "C:\\Coding\\AssettoMiniMap"
local server_port = 8080
local local_ip = "127.0.0.1"
local server_running = false
local last_check = 0
local last_lighting_check = 0

-- Find local IP on startup
local function detectLocalIP()
  local p = io.popen("powershell -Command \"(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' | Where-Object {$_.IPAddress -notlike '169.254*'} | Select-Object -First 1).IPAddress\"")
  if p then
    local res = p:read("*a")
    p:close()
    if res and #res > 6 then
      local_ip = res:gsub("%s+", "")
    end
  end
end

-- Check if port 8080 is listening
local function checkServerStatus()
  local p = io.popen('powershell -Command "Test-NetConnection -ComputerName 127.0.0.1 -Port ' .. server_port .. ' -InformationLevel Quiet"')
  if p then
    local res = p:read("*a")
    p:close()
    if res and res:find("True") then
      server_running = true
      return true
    end
  end
  server_running = false
  return false
end

-- Start server in background
local function startServer()
  local cmd = 'start "" /B powershell -WindowStyle Hidden -Command "cd \\"' .. server_dir .. '\\"; & \\"$env:USERPROFILE\\.local\\bin\\uv.exe\\" run backend/server.py"'
  os.execute(cmd)
  server_running = true
end

-- Stop server
local function stopServer()
  os.execute('taskkill /F /IM python.exe /FI "WINDOWTITLE eq *server.py*" 2>nul')
  server_running = false
end

-- Initial boot sequence
setTimeout(function()
  detectLocalIP()
  if not checkServerStatus() then
    startServer()
    setTimeout(function()
      checkServerStatus()
    end, 2.0)
  end
end, 0.5)

-- Main in-game UI Window
function windowMain(dt)
  ui.pushFont(ui.Font.Title)
  ui.text("Assetto GPS Minimap")
  ui.popFont()
  ui.separator()

  -- Status Indicator
  ui.text("Server Status: ")
  ui.sameLine()
  if server_running then
    ui.textColored("ONLINE", rgbm(0.2, 1.0, 0.4, 1.0))
  else
    ui.textColored("OFFLINE", rgbm(1.0, 0.3, 0.3, 1.0))
  end

  -- Phone URL & Copy Button
  local phone_url = "http://" .. local_ip .. ":" .. server_port
  ui.text("Phone URL:")
  ui.sameLine()
  ui.textColored(phone_url, rgbm(0.22, 0.74, 0.97, 1.0))

  if ui.button("Copy URL", vec2(120, 26)) then
    ui.setClipboardText(phone_url)
  end

  ui.sameLine()
  if server_running then
    if ui.button("Stop Server", vec2(120, 26)) then
      stopServer()
    end
  else
    if ui.button("Start Server", vec2(120, 26)) then
      startServer()
    end
  end

  ui.separator()
  local car = ac.getCar(0)
  local headlights = car and car.headlightsActive
  ui.text("Headlights Sensor: ")
  ui.sameLine()
  if headlights then
    ui.textColored("ON (Night Mode)", rgbm(0.38, 0.74, 0.97, 1.0))
  else
    ui.textColored("OFF (Day Mode)", rgbm(0.95, 0.8, 0.2, 1.0))
  end
end

-- Periodic update loop
function script.update(dt)
  local now = os.clock()

  if now - last_lighting_check > 0.1 then
    last_lighting_check = now
    local car = ac.getCar(0)
    if car and server_running then
      local headlights = car.headlightsActive
      web.post('http://127.0.0.1:' .. server_port .. '/api/environment', {
        headers = { ['Content-Type'] = 'application/json' },
        body = string.format('{"headlights": %s, "isNight": %s, "source": "csp-lua"}',
          headlights and "true" or "false",
          headlights and "true" or "false"
        )
      })
    end
  end

  if now - last_check > 3.0 then
    last_check = now
    checkServerStatus()
  end
end
