"""Run the actual companion script with simulated CSP I/O (test-only lupa)."""

from pathlib import Path

from lupa.luajit21 import LuaRuntime


SOURCE = Path(__file__).resolve().parents[1] / "ac_app/lua/AssettoGPS/AssettoGPS.lua"


def companion(port=8080):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().selectedPort = port
    lua.execute('''
        now = 0
        timers = {}
        requests = {}
        requestHeaders = {}
        messages = {}
        clicked = nil
        alive = false
        missing = false
        statusBody = '{"localIp":"192.168.1.20","httpUrl":null,"httpsUrl":"https://192.168.1.20:8080"}'
        script = {}
        ac = {FolderID = {ScriptOrigin = 1}}
        ac.getFolder = function() return '/app' end
        ac.storage = function(defaults) defaults.serverPort = selectedPort; return defaults end
        ac.getSim = function() return nil end
        ac.getCar = function() return nil end
        io.fileExists = function() return not missing end
        os.clock = function() return now end
        os.runConsoleProcess = function(options, callback)
            launched = options
            exited = callback
        end
        setTimeout = function(callback) table.insert(timers, callback) end
        web = {}
        web.get = function(url, headers, callback)
            assert(url:sub(1, 17) == 'http://127.0.0.1:', 'CSP control must not need TLS support')
            if type(headers) == 'function' then callback, headers = headers, nil end
            table.insert(requests, url)
            table.insert(requestHeaders, headers or {})
            if alive then callback(nil, {status = 200, body = statusBody})
            else callback('connection refused', nil) end
        end
        web.post = function(url, headers, body, callback)
            assert(url:sub(1, 17) == 'http://127.0.0.1:', 'CSP control must not need TLS support')
            table.insert(requests, url)
            table.insert(requestHeaders, headers or {})
            callback(nil, {status = 200})
        end
        rgbm = function() return {} end
        vec2 = function() return {} end
        ui = {Font = {Title = 1}, InputTextFlags = {CharsDecimal = 1}}
        ui.inputText = function(_, value) return value, false, false end
        ui.button = function(label) return clicked == label end
        ui.setClipboardText = function(value) copied = value end
        for _, name in ipairs({'text', 'textColored', 'textWrapped', 'textDisabled'}) do
            ui[name] = function(value) table.insert(messages, value) end
        end
        setmetatable(ui, {__index = function() return function() end end})
        draw = function()
            messages = {}
            windowMain(0.1)
            clicked = nil
            return table.concat(messages, '\\n')
        end
    ''')
    lua.execute(SOURCE.read_text(encoding="utf-8"))
    return lua, lua.globals()


def main():
    lua, app = companion()
    assert "Waiting for server..." in app.draw()
    assert "http://" not in app.draw()
    lua.execute("timers[1]()")
    assert list(app.launched.arguments.values()) == [
        "--port", "8080", "--host", "0.0.0.0", "--control-port", "8081"
    ]
    assert "STARTING" in app.draw()
    app.now = 31
    app.script.update(0.1)
    assert "ERROR" in app.draw() and "30 seconds" in app.draw()
    assert "http://" not in app.draw()

    # A late successful heartbeat recovers from timeout without another process.
    app.alive = True
    app.now = 36
    app.script.update(0.1)
    assert "ONLINE" in app.draw() and "https://192.168.1.20:8080" in app.draw()
    app.clicked = "Copy URL"
    app.draw()
    assert app.copied == "https://192.168.1.20:8080"
    app.clicked = "Stop Server"
    app.draw()
    assert list(app.requests.values())[-1] == "http://127.0.0.1:8081/api/shutdown"

    # TLS failure leaves local controls usable without advertising a dead URL.
    lua, app = companion()
    lua.execute("timers[1]()")
    app.alive = True
    app.statusBody = '{"httpUrl":null,"httpsUrl":null}'
    app.now = 41
    app.script.update(0.1)
    display = app.draw()
    assert "HTTPS unavailable" in display and "https://" not in display
    app.clicked = "Stop Server"
    app.draw()
    assert list(app.requests.values())[-1] == "http://127.0.0.1:8081/api/shutdown"
    assert list(app.requests.values())[-2:] == [
        "http://127.0.0.1:8081/api/status",
        "http://127.0.0.1:8081/api/shutdown",
    ]

    lua, app = companion()
    lua.execute("timers[1]()")
    lua.execute("exited(nil, {exitCode = 3, stderr = 'Address already in use'})")
    assert "ERROR" in app.draw() and "Address already in use" in app.draw()
    assert "Exit code: 3" in app.draw()

    lua, app = companion()
    app.missing = True
    lua.execute("timers[1]()")
    assert "Missing server/AssettoGPS.Server.exe" in app.draw()
    assert app.launched is None
    for port, control_port in ((9000, 9001), (65535, 65534)):
        lua, app = companion(port)
        lua.execute("timers[1]()")
        assert list(app.launched.arguments.values()) == [
            "--port", str(port), "--host", "0.0.0.0", "--control-port", str(control_port)
        ]
        assert list(app.requests.values())[0] == f"http://127.0.0.1:{control_port}/api/status"
    print("Lua companion startup, timeout, recovery, pairing, shutdown and process-error checks passed.")


if __name__ == "__main__":
    main()
