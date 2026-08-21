-- Assetto GPS Companion (CSP Lua App)
-- Native Asynchronous Web/Socket (Zero cmd popups, Zero freezing)

local server_dir = "C:\\Coding\\AssettoMiniMap"
local server_port = 8080
local local_ip = "127.0.0.1"
local server_running = false
local auto_boot_done = false
local manually_stopped = false
local last_check = 0
local last_lighting_check = 0

-- Asynchronously ping local server status
local function checkServerStatus(callback)
  web.get("http://127.0.0.1:" .. server_port .. "/api/status", function(err, response)
    if not err and response and response.status == 200 then
      if not manually_stopped then
        server_running = true
      end
      if response.body then
        local ip = response.body:match('"localIp"%s*:%s*"([^"]+)"')
        if ip and #ip > 6 then
          local_ip = ip
        end
      end
      if callback then callback(true) end
    else
      server_running = false
      if callback then callback(false) end
    end
  end)
end

-- Start server in background via silent detached launcher
local function startServer()
  manually_stopped = false
  server_running = true
  os.execute('wscript.exe "' .. server_dir .. '\\backend\\start_silent.vbs"')
  setTimeout(function()
    checkServerStatus()
  end, 1.5)
end

-- Stop server cleanly via HTTP shutdown endpoint
local function stopServer()
  manually_stopped = true
  server_running = false
  web.get("http://127.0.0.1:" .. server_port .. "/api/shutdown", function(err, response)
    server_running = false
  end)
end

-- One-shot silent auto-boot on startup
setTimeout(function()
  checkServerStatus(function(alive)
    if not alive and not auto_boot_done and not manually_stopped then
      auto_boot_done = true
      startServer()
    end
  end)
end, 1.0)

-- Main in-game UI Window (ImGui)
function windowMain(dt)
  ui.pushFont(ui.Font.Title)
  ui.text("Assetto GPS Minimap")
  ui.popFont()
  ui.separator()

  -- Server Status
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

  if ui.button("Copy URL", vec2(100, 24)) then
    ui.setClipboardText(phone_url)
  end

  ui.sameLine()
  if server_running then
    if ui.button("Stop Server", vec2(100, 24)) then
      stopServer()
    end
  else
    if ui.button("Start Server", vec2(100, 24)) then
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

-- Periodic async update loop
function script.update(dt)
  local now = os.clock()

  -- Sync headlights every 0.1s via async web post
  if now - last_lighting_check > 0.1 then
    last_lighting_check = now
    local car = ac.getCar(0)
    if car and server_running then
      local headlights = car.headlightsActive
      web.post("http://127.0.0.1:" .. server_port .. "/api/environment", {
        headers = { ["Content-Type"] = "application/json" },
        body = string.format('{"headlights": %s, "isNight": %s, "source": "csp-lua"}',
          headlights and "true" or "false",
          headlights and "true" or "false"
        )
      })
    end
  end

  -- Async heartbeat every 4 seconds (zero blocking)
  if now - last_check > 4.0 then
    last_check = now
    if not manually_stopped then
      checkServerStatus()
    end
  end
end
