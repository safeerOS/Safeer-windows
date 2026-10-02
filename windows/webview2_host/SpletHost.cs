// Safeer Splet na WebView2 (Windows): gostitelj zavihkov brskalnika.
//
// Zakaj: Qt WebEngine (uradna gradnja) nima licencnih zapisov H.264/AAC in DRM, sistemski WebView2 jih ima
// (licence so del Windows). Splet zato na Windows tece na WebView2; Qt (Python) ostane lupina - zavihki,
// naslovna vrstica, scit, zacetna stran. Ta proces drzi vse zavihke: vsak je okno brez okvirja, vstavljeno
// v povrsino Qt (SetParent), z enim skupnim okoljem WebView2 (en profil).
//
// Pogovor s Pythonom: vrstice JSON po stdin (ukazi) in stdout (dogodki). Odlocitve, ki jih pozna samo
// Safeer (scit pred oglasi in groznjami, zacetna stran safeer://, navigacija), vprasamo Python in pocakamo
// na odgovor ("reply"); brez odgovora v roku zahteva stece naprej - stran nikoli ne obvisi.
using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SafeerMediaWebView;

internal static class SpletHost
{
    private static Control invoker = null!;
    private static Stream output = null!;
    private static readonly object writeLock = new();
    private static readonly Dictionary<string, SpletTab> tabs = new();
    private static readonly ConcurrentDictionary<string, TaskCompletionSource<JsonElement>> waiting = new();
    private static int nextId;

    internal static CoreWebView2Environment Environment = null!;
    internal static bool PrivateMode;
    internal static volatile bool Gpc;
    internal static readonly List<(string Source, bool Start)> Scripts = new();
    internal static readonly HashSet<string> Trusted = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>Odlocitve scita po paru (gostitelj zahteve | gostitelj strani): true = blokiraj.</summary>
    internal static readonly ConcurrentDictionary<string, bool> BlockCache = new();
    internal static readonly Dictionary<string, (CoreWebView2NewWindowRequestedEventArgs Args, CoreWebView2Deferral Deferral)> PendingWindows = new();

    internal static void Run(Dictionary<string, string> values)
    {
        output = Console.OpenStandardOutput();
        invoker = new Control();
        _ = invoker.Handle;
        PrivateMode = values.TryGetValue("private", out var p) && p == "1";
        var profile = values.TryGetValue("profile", out var pr) && !string.IsNullOrWhiteSpace(pr)
            ? pr : Path.Combine(Path.GetTempPath(), "SafeerSplet");
        var extra = values.TryGetValue("flags", out var f) ? f : "";
        invoker.BeginInvoke(new Action(async () =>
        {
            try
            {
                Directory.CreateDirectory(profile);
                var scheme = new CoreWebView2CustomSchemeRegistration("safeer") { TreatAsSecure = true, HasAuthorityComponent = true };
                var language = values.TryGetValue("lang", out var lang) && lang.Length is >= 2 and <= 12 ? lang : null;
                var options = new CoreWebView2EnvironmentOptions(("--disable-background-mode " + extra).Trim(), language, null, false,
                    new List<CoreWebView2CustomSchemeRegistration> { scheme });
                Environment = await CoreWebView2Environment.CreateAsync(null, profile, options);
                Send(new { ev = "ready", version = Environment.BrowserVersionString });
            }
            catch (Exception e)
            {
                Send(new { ev = "fatal", detail = e.GetType().Name + ": " + e.Message });
                Application.Exit();
            }
        }));
        new Thread(ReadLoop) { IsBackground = true, Name = "safeer-splet-stdin" }.Start();
        Application.Run();
    }

    private static void ReadLoop()
    {
        try
        {
            using var reader = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
            string? line;
            while ((line = reader.ReadLine()) != null)
            {
                JsonElement msg;
                try { msg = JsonDocument.Parse(line).RootElement.Clone(); } catch { continue; }
                var cmd = Str(msg, "cmd");
                if (cmd == "reply")
                {
                    // Odgovor na vprasanje: neposredno iz bralne niti (nit vmesnika morda prav zdaj caka nanj).
                    if (waiting.TryRemove(Str(msg, "id"), out var t)) t.TrySetResult(msg);
                    continue;
                }
                var kopija = msg;
                invoker.BeginInvoke(new Action(() => { try { Handle(cmd, kopija); } catch (Exception e) { Send(new { ev = "error", cmd, detail = e.Message }); } }));
            }
        }
        catch { }
        // Python se je zaprl (stdin konec): ugasnemo tudi mi, brez osirotelih procesov.
        try { invoker.BeginInvoke(new Action(Application.Exit)); } catch { System.Environment.Exit(0); }
    }

    internal static string Str(JsonElement e, string name) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    internal static bool Bool(JsonElement e, string name) =>
        e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.True;

    internal static void Send(object payload)
    {
        try
        {
            var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload) + "\n");
            lock (writeLock) { output.Write(bytes, 0, bytes.Length); output.Flush(); }
        }
        catch { }
    }

    internal static string NextId() => Interlocked.Increment(ref nextId).ToString();

    /// <summary>Vprasanje Pythonu; odgovor pride kot {"cmd":"reply","id":...}.</summary>
    internal static Task<JsonElement> Ask(string id, object payload)
    {
        var tcs = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        waiting[id] = tcs;
        Send(payload);
        return tcs.Task;
    }

    internal static async Task<JsonElement?> AskAsync(string id, object payload, int timeoutMs)
    {
        var task = Ask(id, payload);
        if (await Task.WhenAny(task, Task.Delay(timeoutMs)) == task) return task.Result;
        waiting.TryRemove(id, out _);
        return null;
    }

    internal static JsonElement? AskSync(string id, object payload, int timeoutMs)
    {
        var task = Ask(id, payload);
        try { if (task.Wait(timeoutMs)) return task.Result; } catch { }
        waiting.TryRemove(id, out _);
        return null;
    }

    private static void Handle(string cmd, JsonElement msg)
    {
        var id = Str(msg, "tab");
        if (cmd == "config")
        {
            Gpc = Bool(msg, "gpc");
            if (msg.TryGetProperty("scripts", out var list) && list.ValueKind == JsonValueKind.Array)
            {
                Scripts.Clear();
                foreach (var s in list.EnumerateArray()) Scripts.Add((Str(s, "source"), Bool(s, "start")));
            }
            if (msg.TryGetProperty("trusted", out var tr) && tr.ValueKind == JsonValueKind.Array)
            {
                Trusted.Clear();
                foreach (var s in tr.EnumerateArray()) if (s.ValueKind == JsonValueKind.String) Trusted.Add(s.GetString() ?? "");
            }
            BlockCache.Clear();
            return;
        }
        if (cmd == "create")
        {
            if (tabs.ContainsKey(id) || !msg.TryGetProperty("parent", out var ph) || !ph.TryGetInt64(out var parent)) return;
            var req = Str(msg, "req");
            (CoreWebView2NewWindowRequestedEventArgs Args, CoreWebView2Deferral Deferral)? pending = null;
            if (req.Length > 0 && PendingWindows.Remove(req, out var found)) pending = found;
            var tab = new SpletTab(id, new IntPtr(parent), Str(msg, "url"), pending);
            tabs[id] = tab;
            tab.Show();
            return;
        }
        if (cmd == "dropwindow")
        {
            if (PendingWindows.Remove(Str(msg, "req"), out var dropped))
            {
                try { dropped.Args.Handled = true; dropped.Deferral.Complete(); } catch { }
            }
            return;
        }
        if (cmd == "quit") { Application.Exit(); return; }
        if (!tabs.TryGetValue(id, out var target)) return;
        if (cmd == "close")
        {
            tabs.Remove(id);
            target.Shutdown();
            return;
        }
        target.Command(cmd, msg);
    }
}

internal sealed class SpletTab : Form
{
    private const int GwlStyle = -16;
    private const long WsChild = 0x40000000L;
    private const long WsPopup = 0x80000000L;

    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetParent(IntPtr child, IntPtr parent);
    [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr handle);
    [DllImport("user32.dll", SetLastError = true)] private static extern bool MoveWindow(IntPtr handle, int x, int y, int width, int height, bool repaint);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern IntPtr GetWindowLongPtr(IntPtr handle, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern IntPtr SetWindowLongPtr(IntPtr handle, int index, IntPtr value);
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }

    // Most strani -> Safeer: skripte Safeerja pisejo console.log("__safeer_bridge__:{...}") (isto kot v Qt). Tu to
    // prestrezemo in posljemo gostitelju; iz okvirjev gre prek vrhnje strani.
    private const string BridgeScript = @"(() => {
      if (window.__safeerBridgeHook) return; window.__safeerBridgeHook = true;
      const P = '__safeer_bridge__:';
      const send = (text) => {
        try { if (window.chrome && window.chrome.webview) { window.chrome.webview.postMessage(text); return; } } catch (_) {}
        try { if (window.top && window.top !== window) window.top.postMessage({ __safeerBridge: text }, '*'); } catch (_) {}
      };
      const izvirni = console.log;
      console.log = function (...args) {
        try { if (typeof args[0] === 'string' && args[0].startsWith(P)) { send(args[0]); return; } } catch (_) {}
        return izvirni.apply(console, args);
      };
      if (window.top === window) window.addEventListener('message', (e) => {
        try { const d = e.data; if (d && typeof d.__safeerBridge === 'string' && d.__safeerBridge.startsWith(P)) send(d.__safeerBridge); } catch (_) {}
      });
    })();";

    private readonly string id;
    private readonly IntPtr parentHandle;
    private readonly string initialUrl;
    private (CoreWebView2NewWindowRequestedEventArgs Args, CoreWebView2Deferral Deferral)? pendingWindow;
    private readonly WebView2 view = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(7, 11, 18) };
    private readonly System.Windows.Forms.Timer fitTimer = new() { Interval = 150 };
    private int lastWidth = -1, lastHeight = -1;
    private bool closed;
    private readonly List<JsonElement> queued = new();

    internal SpletTab(string tabId, IntPtr parent, string url, (CoreWebView2NewWindowRequestedEventArgs, CoreWebView2Deferral)? pending)
    {
        id = tabId;
        parentHandle = parent;
        initialUrl = url;
        pendingWindow = pending;
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.Manual;
        Location = new Point(-32000, -32000);   // do vstavitve v Safeer nevidno (brez utripa samostojnega okna)
        Size = new Size(8, 8);
        BackColor = Color.FromArgb(7, 11, 18);
        Controls.Add(view);
        Load += async (_, _) => await InitializeAsync();
        Shown += (_, _) => Attach();
        fitTimer.Tick += (_, _) => Fit(false);
        view.KeyDown += OnAcceleratorKey;
        // Fokus je presel v spletno stran: lupina (Qt) tega sama ne izve, ker je stran okno drugega procesa.
        view.GotFocus += (_, _) => SpletHost.Send(new { ev = "gotfocus", tab = id });
    }

    protected override bool ShowWithoutActivation => true;

    private void Attach()
    {
        var style = GetWindowLongPtr(Handle, GwlStyle).ToInt64();
        style = (style | WsChild) & ~WsPopup;
        SetWindowLongPtr(Handle, GwlStyle, new IntPtr(style));
        SetParent(Handle, parentHandle);
        Fit(true);
        fitTimer.Start();
    }

    private void Fit(bool force)
    {
        if (closed) return;
        if (!IsWindow(parentHandle)) { SpletHost.Send(new { ev = "orphan", tab = id }); Shutdown(); return; }
        if (!GetClientRect(parentHandle, out var area)) return;
        int w = Math.Max(1, area.Right - area.Left), h = Math.Max(1, area.Bottom - area.Top);
        if (!force && w == lastWidth && h == lastHeight) return;
        lastWidth = w; lastHeight = h;
        MoveWindow(Handle, 0, 0, w, h, true);
    }

    internal void Shutdown()
    {
        if (closed) return;
        closed = true;
        fitTimer.Stop();
        if (pendingWindow is { } p) { try { p.Args.Handled = true; p.Deferral.Complete(); } catch { } pendingWindow = null; }
        try { view.Dispose(); } catch { }
        try { Close(); } catch { }
    }

    private CoreWebView2? Core => closed ? null : view.CoreWebView2;

    private async Task InitializeAsync()
    {
        try
        {
            var controllerOptions = SpletHost.Environment.CreateCoreWebView2ControllerOptions();
            controllerOptions.IsInPrivateModeEnabled = SpletHost.PrivateMode;
            await view.EnsureCoreWebView2Async(SpletHost.Environment, controllerOptions);
            var core = view.CoreWebView2;
            var settings = core.Settings;
            settings.IsStatusBarEnabled = true;
            settings.AreDevToolsEnabled = true;
            settings.AreDefaultContextMenusEnabled = true;
            settings.AreBrowserAcceleratorKeysEnabled = true;
            settings.IsZoomControlEnabled = true;
            settings.IsWebMessageEnabled = true;
            settings.AreHostObjectsAllowed = false;
            settings.IsPasswordAutosaveEnabled = false;
            settings.IsGeneralAutofillEnabled = !SpletHost.PrivateMode;

            await core.AddScriptToExecuteOnDocumentCreatedAsync(BridgeScript);
            foreach (var (source, start) in SpletHost.Scripts)
            {
                var code = start ? source
                    : "(() => { const zazeni = () => { try { " + source + "\n } catch (e) {} };"
                      + " if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', zazeni, { once: true }); else zazeni(); })();";
                try { await core.AddScriptToExecuteOnDocumentCreatedAsync(code); } catch { }
            }

            core.SourceChanged += (_, _) => SpletHost.Send(new { ev = "url", tab = id, url = core.Source });
            core.DocumentTitleChanged += (_, _) => SpletHost.Send(new { ev = "title", tab = id, title = core.DocumentTitle });
            core.HistoryChanged += (_, _) => SpletHost.Send(new { ev = "history", tab = id, back = core.CanGoBack, forward = core.CanGoForward });
            core.NavigationStarting += OnNavigationStarting;
            core.NavigationCompleted += (_, e) =>
                SpletHost.Send(new { ev = "loading", tab = id, on = false, ok = e.IsSuccess, status = e.WebErrorStatus.ToString(), url = core.Source });
            core.NewWindowRequested += OnNewWindow;
            core.ContainsFullScreenElementChanged += (_, _) =>
                SpletHost.Send(new { ev = "fullscreen", tab = id, on = core.ContainsFullScreenElement });
            core.WindowCloseRequested += (_, _) => SpletHost.Send(new { ev = "closerequested", tab = id });
            core.ProcessFailed += (_, e) => SpletHost.Send(new { ev = "crashed", tab = id, kind = e.ProcessFailedKind.ToString() });
            core.WebMessageReceived += (_, e) => OnMessage(e);
            core.FrameCreated += (_, e) => { try { e.Frame.WebMessageReceived += (_, m) => OnMessage(m); } catch { } };
            core.FaviconChanged += async (_, _) => await SendFaviconAsync();
            core.ServerCertificateErrorDetected += OnCertificateError;
            core.DownloadStarting += OnDownload;
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += OnResource;

            SpletHost.Send(new { ev = "created", tab = id });
            if (pendingWindow is { } p)
            {
                pendingWindow = null;
                try { p.Args.NewWindow = core; p.Args.Handled = true; } catch { }
                try { p.Deferral.Complete(); } catch { }
            }
            else if (!string.IsNullOrWhiteSpace(initialUrl)) core.Navigate(initialUrl);
            foreach (var m in queued) Command(SpletHost.Str(m, "cmd"), m);
            queued.Clear();
        }
        catch (Exception e)
        {
            SpletHost.Send(new { ev = "tabfailed", tab = id, detail = e.GetType().Name + ": " + e.Message });
        }
    }

    internal void Command(string cmd, JsonElement msg)
    {
        var core = Core;
        if (core is null) { if (!closed) queued.Add(msg); return; }
        switch (cmd)
        {
            case "navigate":
                var url = SpletHost.Str(msg, "url");
                if (url.Length > 0) { try { core.Navigate(url); } catch { SpletHost.Send(new { ev = "loading", tab = id, on = false, ok = false, status = "InvalidUrl", url }); } }
                break;
            case "back": if (core.CanGoBack) core.GoBack(); break;
            case "forward": if (core.CanGoForward) core.GoForward(); break;
            case "reload": core.Reload(); break;
            case "stop": core.Stop(); break;
            case "focus": try { view.Focus(); } catch { } break;
            case "fit": Fit(true); break;
            case "devtools": core.OpenDevToolsWindow(); break;
            case "print": try { core.ShowPrintUI(); } catch { } break;
            case "zoom":
                if (msg.TryGetProperty("factor", out var z) && z.TryGetDouble(out var factor)) view.ZoomFactor = Math.Clamp(factor, 0.25, 5.0);
                break;
            case "mute": core.IsMuted = SpletHost.Bool(msg, "on"); break;
            case "downloads": try { core.OpenDefaultDownloadDialog(); } catch { } break;
            case "cleardata": _ = ClearDataAsync(core); break;
            case "exec":
                _ = ExecAsync(core, SpletHost.Str(msg, "id"), SpletHost.Str(msg, "js"));
                break;
        }
    }

    private static async Task ClearDataAsync(CoreWebView2 core)
    {
        // Piskotki, predpomnilnik, zgodovina, shramba strani - za ves profil (vsi zavihki).
        try { await core.Profile.ClearBrowsingDataAsync(); } catch { }
    }

    private async Task ExecAsync(CoreWebView2 core, string execId, string js)
    {
        string value = "null";
        try { value = await core.ExecuteScriptAsync(js); } catch { }
        if (execId.Length > 0) SpletHost.Send(new { ev = "result", tab = id, id = execId, value });
    }

    private void OnNavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        var uri = e.Uri ?? "";
        var scheme = Uri.TryCreate(uri, UriKind.Absolute, out var parsed) ? parsed.Scheme.ToLowerInvariant() : "";
        if (scheme is not ("http" or "https" or "safeer" or "about" or "blob" or "data" or "file" or "edge" or "devtools" or "view-source"))
        {
            // magnet:, mailto:, tel:, file: ... odloci Safeer (magnet v Medijski center, posta v privzeti program).
            e.Cancel = true;
            SpletHost.Send(new { ev = "external", tab = id, url = uri, user = e.IsUserInitiated });
            return;
        }
        if (scheme is "http" or "https")
        {
            var ask = SpletHost.NextId();
            var reply = SpletHost.AskSync(ask, new { ev = "nav", id = ask, tab = id, url = uri, user = e.IsUserInitiated, redirect = e.IsRedirected }, 500);
            if (reply is { } r && r.TryGetProperty("allow", out var allow) && allow.ValueKind == JsonValueKind.False)
            {
                e.Cancel = true;
                return;
            }
        }
        SpletHost.Send(new { ev = "loading", tab = id, on = true, url = uri });
    }

    private void OnNewWindow(object? sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        var req = SpletHost.NextId();
        CoreWebView2Deferral deferral;
        try { deferral = e.GetDeferral(); } catch { e.Handled = true; return; }
        SpletHost.PendingWindows[req] = (e, deferral);
        SpletHost.Send(new { ev = "newwindow", tab = id, req, url = e.Uri ?? "", user = e.IsUserInitiated });
        // Safeer v 5 s ni odprl zavihka: okna ne odpremo (brez visecih zahtev).
        var timer = new System.Windows.Forms.Timer { Interval = 5000 };
        timer.Tick += (_, _) =>
        {
            timer.Stop(); timer.Dispose();
            if (SpletHost.PendingWindows.Remove(req, out var stale)) { try { stale.Args.Handled = true; stale.Deferral.Complete(); } catch { } }
        };
        timer.Start();
    }

    private void OnMessage(CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            var text = e.TryGetWebMessageAsString();
            if (!string.IsNullOrEmpty(text) && text.Length < 200_000)
                SpletHost.Send(new { ev = "message", tab = id, data = text, source = e.Source ?? "" });
        }
        catch { }
    }

    private async Task SendFaviconAsync()
    {
        try
        {
            var core = Core;
            if (core is null) return;
            using var stream = await core.GetFaviconAsync(CoreWebView2FaviconImageFormat.Png);
            using var memory = new MemoryStream();
            await stream.CopyToAsync(memory);
            if (memory.Length is > 0 and < 200_000)
                SpletHost.Send(new { ev = "icon", tab = id, png = Convert.ToBase64String(memory.ToArray()) });
        }
        catch { }
    }

    private void OnCertificateError(object? sender, CoreWebView2ServerCertificateErrorDetectedEventArgs e)
    {
        // Samo pripeto potrdilo Safeer Huba (enak odtis SHA-256); vse druge napake ostanejo zavrnjene.
        try
        {
            var der = e.ServerCertificate.ToX509Certificate2().RawData;
            var odtis = Convert.ToHexString(SHA256.HashData(der));
            e.Action = SpletHost.Trusted.Contains(odtis)
                ? CoreWebView2ServerCertificateErrorAction.AlwaysAllow
                : CoreWebView2ServerCertificateErrorAction.Cancel;
        }
        catch { e.Action = CoreWebView2ServerCertificateErrorAction.Cancel; }
    }

    private void OnDownload(object? sender, CoreWebView2DownloadStartingEventArgs e)
    {
        // Prenos vodi WebView2 (mapa Prenosi, lastno okence napredka); Safeer dobi obvestilo za svoj seznam.
        try
        {
            var op = e.DownloadOperation;
            var path = e.ResultFilePath ?? "";
            SpletHost.Send(new { ev = "download", tab = id, state = "started", url = op.Uri ?? "", path });
            op.StateChanged += (_, _) =>
            {
                if (op.State != CoreWebView2DownloadState.InProgress)
                    SpletHost.Send(new { ev = "download", tab = id, state = op.State == CoreWebView2DownloadState.Completed ? "done" : "failed", url = op.Uri ?? "", path = op.ResultFilePath ?? path });
            };
        }
        catch { }
    }

    private void OnAcceleratorKey(object? sender, KeyEventArgs e)
    {
        // Bliznjice lupine (zavihki, naslovna vrstica) gredo Safeerju; ostale (Ctrl+F, F5, Ctrl+P, povecava, F12) opravi WebView2 sam.
        var k = e.KeyCode;
        bool forward =
            (e.Control && !e.Alt && (k is Keys.T or Keys.W or Keys.L or Keys.D or Keys.N or Keys.Tab or Keys.F4 or Keys.PageDown or Keys.PageUp
                                     || (k >= Keys.D1 && k <= Keys.D9)))
            || (e.Alt && !e.Control && (k is Keys.D or Keys.Home))
            || (!e.Control && !e.Alt && (k is Keys.F6 or Keys.F11));
        if (!forward) return;
        e.Handled = true;
        e.SuppressKeyPress = true;
        SpletHost.Send(new { ev = "key", tab = id, code = (int)k, ctrl = e.Control, shift = e.Shift, alt = e.Alt });
    }

    private static string HostOf(string url) => Uri.TryCreate(url, UriKind.Absolute, out var u) ? u.Host.ToLowerInvariant() : "";

    private async void OnResource(object? sender, CoreWebView2WebResourceRequestedEventArgs e)
    {
        var core = Core;
        if (core is null) return;
        var uri = e.Request.Uri ?? "";
        if (uri.StartsWith("safeer://", StringComparison.OrdinalIgnoreCase))
        {
            // Zacetna stran in strani Safeerja (blokirano, opozorilo): vsebino da Python (ista koda kot v Qt).
            var deferral = e.GetDeferral();
            try
            {
                var ask = SpletHost.NextId();
                var reply = await SpletHost.AskAsync(ask, new { ev = "resource", id = ask, tab = id, url = uri }, 4000);
                if (reply is { } r && SpletHost.Str(r, "data").Length > 0)
                {
                    var bytes = Convert.FromBase64String(SpletHost.Str(r, "data"));
                    var mime = SpletHost.Str(r, "mime");
                    e.Response = SpletHost.Environment.CreateWebResourceResponse(new MemoryStream(bytes), 200, "OK",
                        "Content-Type: " + (mime.Length > 0 ? mime : "application/octet-stream") + "\nCache-Control: no-store");
                }
                else e.Response = SpletHost.Environment.CreateWebResourceResponse(null, 404, "Not Found", "");
            }
            catch { }
            finally { try { deferral.Complete(); } catch { } }
            return;
        }
        if (!uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase) && !uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) return;
        if (SpletHost.Gpc)
        {
            try { e.Request.Headers.SetHeader("Sec-GPC", "1"); e.Request.Headers.SetHeader("DNT", "1"); } catch { }
        }
        var top = core.Source ?? "";
        var key = HostOf(uri) + "|" + HostOf(top);
        if (!SpletHost.BlockCache.TryGetValue(key, out var block))
        {
            var deferral = e.GetDeferral();
            try
            {
                var ask = SpletHost.NextId();
                var reply = await SpletHost.AskAsync(ask, new { ev = "request", id = ask, tab = id, url = uri, first = top }, 1500);
                block = reply is { } r && SpletHost.Bool(r, "block");
                if (reply is not null) SpletHost.BlockCache[key] = block;
                if (block) { try { e.Response = SpletHost.Environment.CreateWebResourceResponse(null, 403, "Blocked", ""); } catch { } }
            }
            catch { }
            finally { try { deferral.Complete(); } catch { } }
            return;
        }
        if (block) { try { e.Response = SpletHost.Environment.CreateWebResourceResponse(null, 403, "Blocked", ""); } catch { } }
    }
}
