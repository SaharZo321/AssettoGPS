-- Assetto GPS Companion (CSP Lua App)
-- Launches the bundled server without machine-specific paths or shell scripts.

local script_dir = ac.getFolder(ac.FolderID.ScriptOrigin)
local server_dir = script_dir .. "/server"
local server_executable = server_dir .. "/AssettoGPS.Server.exe"
local settings = ac.storage({
  serverPort = 8080
})
local server_port = math.floor(tonumber(settings.serverPort) or 8080)
if server_port < 1024 or server_port > 65535 then
  server_port = 8080
  settings.serverPort = server_port
end
local port_input = tostring(server_port)
local port_error = nil
local local_ip = "127.0.0.1"
local server_running = false
local launch_in_progress = false
local launch_error = nil
local auto_boot_done = false
local manually_stopped = false
local last_check = 0
local last_lighting_check = 0
local control_headers = {
  ["Content-Type"] = "application/json",
  ["X-AssettoGPS-Control"] = "1"
}

local function applyPort()
  local value = tonumber(port_input)
  if not value or value % 1 ~= 0 or value < 1024 or value > 65535 then
    port_error = "Enter a whole-number port from 1024 to 65535."
    return
  end

  server_port = math.floor(value)
  settings.serverPort = server_port
  port_input = tostring(server_port)
  port_error = nil
end

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

-- Start the packaged server as a CSP-managed background process.
local function startServer()
  if launch_in_progress then return end
  manually_stopped = false
  launch_error = nil

  if not io.fileExists(server_executable) then
    server_running = false
    launch_error = "Missing server/AssettoGPS.Server.exe. Reinstall the release package."
    return
  end

  launch_in_progress = true
  os.runConsoleProcess({
    filename = server_executable,
    arguments = {"--port", tostring(server_port)},
    workingDirectory = server_dir,
    assignJob = true
  }, function(err, data)
    launch_in_progress = false
    server_running = false
    if err then
      launch_error = tostring(err)
    end
  end)

  setTimeout(function()
    checkServerStatus()
  end, 1.5)
end

-- Stop server cleanly via HTTP shutdown endpoint
local function stopServer()
  manually_stopped = true
  server_running = false
  web.post("http://127.0.0.1:" .. server_port .. "/api/shutdown",
    control_headers, "", function(err, response)
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
  elseif launch_in_progress then
    ui.textColored("STARTING", rgbm(0.95, 0.8, 0.2, 1.0))
  else
    ui.textColored("OFFLINE", rgbm(1.0, 0.3, 0.3, 1.0))
  end

  if launch_error then
    ui.textWrapped("Server error: " .. launch_error)
  end

  -- Port changes are only allowed while the server process is stopped.
  local port_locked = server_running or launch_in_progress
  ui.text("Server Port:")
  ui.sameLine()
  if port_locked then ui.pushDisabled() end
  ui.setNextItemWidth(72)
  local port_changed
  local port_submitted
  port_input, port_changed, port_submitted = ui.inputText(
    "##serverPort", port_input, ui.InputTextFlags.CharsDecimal)
  ui.sameLine()
  local apply_port_clicked = ui.button("Apply", vec2(62, 0))
  if port_locked then ui.popDisabled() end

  if not port_locked and (port_submitted or apply_port_clicked) then
    applyPort()
  end
  local port_dirty = port_input ~= tostring(server_port)
  if port_locked then
    ui.textDisabled("Stop the server to change the port.")
  elseif port_error then
    ui.textColored(port_error, rgbm(1.0, 0.35, 0.3, 1.0))
  elseif port_dirty then
    ui.textDisabled("Apply the port before starting the server.")
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
    if port_dirty then ui.pushDisabled() end
    if ui.button("Start Server", vec2(100, 24)) then
      startServer()
    end
    if port_dirty then ui.popDisabled() end
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
      local body = string.format('{"headlights": %s, "isNight": %s, "source": "csp-lua"}',
          headlights and "true" or "false",
          headlights and "true" or "false"
        )
      web.post("http://127.0.0.1:" .. server_port .. "/api/environment",
        control_headers, body, function(err, response) end)
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
