using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace SafeerMediaWebView;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var values = args.Select(x => x.Split('=', 2))
            .Where(x => x.Length == 2 && x[0].StartsWith("--"))
            .ToDictionary(x => x[0][2..], x => x[1], StringComparer.OrdinalIgnoreCase);
        if (!values.TryGetValue("parent", out var parentText)
            || !long.TryParse(parentText, out var parentValue)
            || !values.TryGetValue("url", out var url)
            || !Uri.TryCreate(url, UriKind.Absolute, out var mediaUri)
            || mediaUri.Scheme != Uri.UriSchemeHttps)
        {
            Environment.ExitCode = 2;
            return;
        }
        values.TryGetValue("profile", out var profile);
        values.TryGetValue("state", out var state);
        values.TryGetValue("command", out var command);
        Application.Run(new MediaForm(new IntPtr(parentValue), mediaUri,
            profile ?? Path.Combine(Path.GetTempPath(), "SafeerMediaWebView"), state ?? "", command ?? ""));
    }
}

internal sealed class MediaForm : Form
{
    private readonly IntPtr parentHandle;
    private readonly Uri initialUri;
    private readonly string profilePath;
    private readonly string statePath;
    private readonly string commandPath;
    private readonly WebView2 view = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.Black };
    private readonly System.Windows.Forms.Timer fitTimer = new() { Interval = 250 };
    private readonly System.Windows.Forms.Timer commandTimer = new() { Interval = 200 };
    private readonly System.Windows.Forms.Timer playbackTimer = new() { Interval = 750 };
    private readonly System.Windows.Forms.Timer inputTimer = new() { Interval = 2500 };
    private readonly List<CoreWebView2Frame> frames = new();
    private readonly HashSet<string> mediaRequestUrls = new(StringComparer.OrdinalIgnoreCase);
    private bool mediaResponseLogged;
    private bool playbackStarted;
    private bool playbackCheckRunning;
    private int playClickAttempts;
    private CoreWebView2DevToolsProtocolEventReceiver? networkResponseReceiver;

    private const string PlaybackCheckScript =
        "(() => Array.from(document.querySelectorAll('video,audio')).some(m => !m.paused && !m.ended && m.readyState >= 2 && m.currentTime > 0))()";
    private const string AutoplayScript = @"(() => {
      if (window.__safeerAutoplayInstalled) return true;
      window.__safeerAutoplayInstalled = true;
      const play = () => {
        document.querySelectorAll('video,audio').forEach(m => {
          try { m.muted = false; m.volume = 1.0; const p = m.play(); if (p) p.catch(() => {}); } catch (_) {}
        });
        const b = document.querySelector('[aria-label=""Play""], [title=""Play""], .vjs-big-play-button, .jw-icon-display, .plyr__control--overlaid, [data-plyr=""play""], .play-button');
        if (b) { try { b.click(); } catch (_) {} }
      };
      const subtitlesOff = () => document.querySelectorAll('video').forEach(v => {
        try { Array.from(v.textTracks || []).forEach(t => { t.mode = 'disabled'; }); } catch (_) {}
      });
      const poke = () => {
        play();
        const media = Array.from(document.querySelectorAll('video,audio'));
        if (!media.some(m => !m.paused && m.readyState >= 2)) {
          const e = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
          if (e) { try { e.click(); } catch (_) {} }
          setTimeout(play, 300);
        }
      };
      subtitlesOff(); setTimeout(subtitlesOff, 800); setTimeout(subtitlesOff, 2200);
      play(); setTimeout(play, 1200); setTimeout(play, 3000);
      setTimeout(poke, 4500); setTimeout(poke, 7000); setTimeout(poke, 9500);
      return true;
    })();";

    private const int GwlStyle = -16;
    private const long WsChild = 0x40000000L;
    private const long WsPopup = 0x80000000L;

    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetParent(IntPtr child, IntPtr parent);
    [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr handle, out Rect rect);
    [DllImport("user32.dll", SetLastError = true)] private static extern bool MoveWindow(IntPtr handle, int x, int y, int width, int height, bool repaint);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern IntPtr GetWindowLongPtr(IntPtr handle, int index);
    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern IntPtr SetWindowLongPtr(IntPtr handle, int index, IntPtr value);

    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }

    internal MediaForm(IntPtr parent, Uri uri, string profile, string state, string command)
    {
        parentHandle = parent;
        initialUri = uri;
        profilePath = profile;
        statePath = state;
        commandPath = command;
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        BackColor = Color.Black;
        Controls.Add(view);
        Load += async (_, _) => await InitializeAsync();
        Shown += (_, _) => AttachToSafeer();
        fitTimer.Tick += (_, _) => FitToParent();
        commandTimer.Tick += (_, _) => ProcessCommand();
        playbackTimer.Tick += async (_, _) => await CheckPlaybackAsync();
        inputTimer.Tick += async (_, _) => await DispatchPlayClickAsync();
        FormClosed += (_, _) => { fitTimer.Stop(); commandTimer.Stop(); playbackTimer.Stop(); inputTimer.Stop(); };
    }

    private async Task InitializeAsync()
    {
        try
        {
            Directory.CreateDirectory(profilePath);
            var options = new CoreWebView2EnvironmentOptions(
                "--autoplay-policy=no-user-gesture-required --disable-background-mode --disable-sync");
            var environment = await CoreWebView2Environment.CreateAsync(null, profilePath, options);
            await view.EnsureCoreWebView2Async(environment);
            var core = view.CoreWebView2;
            core.IsMuted = false;
            Log("AUDIO_ENABLED", "unmuted");
            await core.CallDevToolsProtocolMethodAsync("Network.enable", "{}");
            networkResponseReceiver = core.GetDevToolsProtocolEventReceiver("Network.responseReceived");
            networkResponseReceiver.DevToolsProtocolEventReceived += (_, e) => DetectMediaResponse(e.ParameterObjectAsJson);
            var settings = core.Settings;
            settings.AreDevToolsEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;
            settings.AreBrowserAcceleratorKeysEnabled = false;
            settings.IsStatusBarEnabled = false;
            settings.IsZoomControlEnabled = false;
            settings.IsPasswordAutosaveEnabled = false;
            settings.IsGeneralAutofillEnabled = false;
            settings.IsWebMessageEnabled = false;
            settings.AreHostObjectsAllowed = false;

            core.NewWindowRequested += (_, e) => { e.Handled = true; Log("POPUP_BLOCKED"); };
            core.DownloadStarting += (_, e) => { e.Cancel = true; Log("DOWNLOAD_BLOCKED"); };
            core.PermissionRequested += (_, e) => {
                e.State = CoreWebView2PermissionState.Deny;
                e.SavesInProfile = false;
                Log("PERMISSION_BLOCKED", e.PermissionKind.ToString());
            };
            core.NavigationStarting += (_, e) => {
                if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var target)
                    || target.Scheme != Uri.UriSchemeHttps
                    || BaseDomain(target.Host) != BaseDomain(initialUri.Host))
                {
                    e.Cancel = true;
                    Log("NAVIGATION_BLOCKED", SafeHost(e.Uri));
                }
            };
            core.ServerCertificateErrorDetected += (_, e) => {
                e.Action = CoreWebView2ServerCertificateErrorAction.Cancel;
                Log("CERTIFICATE_BLOCKED", SafeHost(e.RequestUri));
            };
            core.ProcessFailed += (_, e) => Log("PROCESS_FAILED", e.ProcessFailedKind.ToString());
            core.FrameCreated += (_, e) => {
                var frame = e.Frame;
                frames.Add(frame);
                frame.Destroyed += (_, _) => frames.Remove(frame);
                frame.NavigationCompleted += async (_, navigation) => {
                    if (!navigation.IsSuccess) return;
                    try { await frame.ExecuteScriptAsync(AutoplayScript); Log("FRAME_READY"); } catch { }
                };
            };
            core.NavigationCompleted += async (_, e) => {
                Log(e.IsSuccess ? "NAVIGATION_OK" : "NAVIGATION_FAILED", e.WebErrorStatus.ToString());
                if (e.IsSuccess)
                {
                    await TriggerAutoplayAsync();
                    playClickAttempts = 0;
                    inputTimer.Start();
                }
            };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (_, e) => {
                if (e.ResourceContext == CoreWebView2WebResourceContext.Media)
                    mediaRequestUrls.Add(e.Request.Uri);
            };
            core.WebResourceResponseReceived += (_, e) => {
                if (mediaResponseLogged || e.Response is null || e.Response.StatusCode < 200 || e.Response.StatusCode >= 300)
                    return;
                var path = "";
                try { path = new Uri(e.Request.Uri).AbsolutePath.ToLowerInvariant(); } catch { }
                var contentType = "";
                try { contentType = e.Response.Headers.GetHeader("Content-Type").ToLowerInvariant(); } catch { }
                var mediaContext = mediaRequestUrls.Remove(e.Request.Uri);
                var mediaPath = path.EndsWith(".m3u8") || path.EndsWith(".mpd") || path.EndsWith(".m4s")
                    || path.EndsWith(".ts") || path.EndsWith(".mp4") || path.EndsWith(".webm");
                var mediaType = contentType.StartsWith("video/") || contentType.StartsWith("audio/")
                    || contentType.Contains("mpegurl") || contentType.Contains("dash+xml");
                if (mediaContext || mediaPath || mediaType)
                {
                    mediaResponseLogged = true;
                    Log("MEDIA_RESPONSE", SafeHost(e.Request.Uri));
                }
            };
            core.Navigate(initialUri.AbsoluteUri);
            Log("SESSION_READY", initialUri.Host);
            commandTimer.Start();
            playbackTimer.Start();
        }
        catch (Exception error)
        {
            Log("START_FAILED", error.GetType().Name + ":" + error.Message);
            Environment.ExitCode = 3;
            Close();
        }
    }

    private async Task TriggerAutoplayAsync()
    {
        if (view.CoreWebView2 is null) return;
        try { await view.CoreWebView2.ExecuteScriptAsync(AutoplayScript); } catch { }
    }

    private async Task CheckPlaybackAsync()
    {
        if (playbackCheckRunning || playbackStarted || view.CoreWebView2 is null) return;
        playbackCheckRunning = true;
        try
        {
            var result = await view.CoreWebView2.ExecuteScriptAsync(PlaybackCheckScript);
            var playing = string.Equals(result, "true", StringComparison.OrdinalIgnoreCase);
            if (!playing)
            {
                foreach (var frame in frames.ToArray())
                {
                    try
                    {
                        result = await frame.ExecuteScriptAsync(PlaybackCheckScript);
                        if (string.Equals(result, "true", StringComparison.OrdinalIgnoreCase)) { playing = true; break; }
                    }
                    catch { }
                }
            }
            if (playing)
            {
                playbackStarted = true;
                Log("PLAYBACK_STARTED", initialUri.Host);
                playbackTimer.Stop();
                inputTimer.Stop();
            }
        }
        catch { }
        finally { playbackCheckRunning = false; }
    }

    private async Task DispatchPlayClickAsync()
    {
        if (playbackStarted || view.CoreWebView2 is null)
        {
            inputTimer.Stop();
            return;
        }
        // En pravi uporabniški klik zažene predvajanje. Ponavljanje bi pri
        // HTML5 predvajalnikih isti video takoj znova ustavilo.
        if (++playClickAttempts > 1)
        {
            inputTimer.Stop();
            return;
        }
        var x = Math.Max(1, view.ClientSize.Width / 2);
        var y = Math.Max(1, view.ClientSize.Height / 2);
        try
        {
            var down = JsonSerializer.Serialize(new { type = "mousePressed", x, y, button = "left", clickCount = 1 });
            var up = JsonSerializer.Serialize(new { type = "mouseReleased", x, y, button = "left", clickCount = 1 });
            await view.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", down);
            await view.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", up);
            Log("PLAY_CLICK", playClickAttempts.ToString());
        }
        catch (Exception error) { Log("PLAY_CLICK_FAILED", error.GetType().Name); }
    }

    private void DetectMediaResponse(string payload)
    {
        if (mediaResponseLogged) return;
        try
        {
            using var data = JsonDocument.Parse(payload);
            var root = data.RootElement;
            var type = root.TryGetProperty("type", out var typeValue) ? typeValue.GetString() ?? "" : "";
            if (!root.TryGetProperty("response", out var response)) return;
            var status = response.TryGetProperty("status", out var statusValue) ? statusValue.GetDouble() : 0;
            var mime = response.TryGetProperty("mimeType", out var mimeValue) ? mimeValue.GetString() ?? "" : "";
            var url = response.TryGetProperty("url", out var urlValue) ? urlValue.GetString() ?? "" : "";
            var isMedia = type.Equals("Media", StringComparison.OrdinalIgnoreCase)
                || mime.StartsWith("video/", StringComparison.OrdinalIgnoreCase)
                || mime.StartsWith("audio/", StringComparison.OrdinalIgnoreCase)
                || mime.Contains("mpegurl", StringComparison.OrdinalIgnoreCase)
                || mime.Contains("dash+xml", StringComparison.OrdinalIgnoreCase);
            if (status >= 200 && status < 300 && isMedia)
            {
                mediaResponseLogged = true;
                Log("MEDIA_RESPONSE", SafeHost(url));
            }
        }
        catch { }
    }

    private void AttachToSafeer()
    {
        var style = GetWindowLongPtr(Handle, GwlStyle).ToInt64();
        style = (style | WsChild) & ~WsPopup;
        SetWindowLongPtr(Handle, GwlStyle, new IntPtr(style));
        SetParent(Handle, parentHandle);
        FitToParent();
        fitTimer.Start();
    }

    private void FitToParent()
    {
        if (!GetClientRect(parentHandle, out var area)) return;
        MoveWindow(Handle, 0, 0, Math.Max(1, area.Right - area.Left), Math.Max(1, area.Bottom - area.Top), true);
    }

    private void ProcessCommand()
    {
        if (string.IsNullOrWhiteSpace(commandPath) || !File.Exists(commandPath) || view.CoreWebView2 is null) return;
        try
        {
            var command = File.ReadAllText(commandPath).Trim().ToLowerInvariant();
            File.Delete(commandPath);
            if (command == "back" && view.CoreWebView2.CanGoBack) view.CoreWebView2.GoBack();
            else if (command == "reload") view.CoreWebView2.Reload();
        }
        catch { }
    }

    private static string BaseDomain(string host)
    {
        var parts = host.Trim('.').ToLowerInvariant().Split('.');
        return parts.Length >= 2 ? string.Join('.', parts[^2..]) : host.ToLowerInvariant();
    }

    private static string SafeHost(string raw) => Uri.TryCreate(raw, UriKind.Absolute, out var uri) ? uri.Host : "invalid";

    private void Log(string type, string detail = "")
    {
        if (string.IsNullOrWhiteSpace(statePath)) return;
        try
        {
            var line = JsonSerializer.Serialize(new { time = DateTimeOffset.UtcNow, type, detail });
            File.AppendAllText(statePath, line + Environment.NewLine);
        }
        catch { }
    }
}
