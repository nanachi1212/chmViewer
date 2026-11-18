using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class ReaderWindow : Form
{
    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length != 2) return 1;
        SetProcessDPIAware();
        Application.EnableVisualStyles();
        using (var form = new ReaderWindow(args[0], args[1]))
            Application.Run(form);
        return Environment.ExitCode;
    }

    private ReaderWindow(string url, string profile)
    {
        Text = "CHM 閱讀器";
        // WinForms 不一定會自動使用 PE 的 Win32 icon；明確指定，讓標題列與工作列
        // 都使用與主程式、檔案關聯相同的莫蘭迪 NNC 圖標。
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
        catch (Exception) { /* 若系統無法讀取資源，仍可正常閱讀。 */ }
        ClientSize = new Size(1200, 800);
        StartPosition = FormStartPosition.CenterScreen;
        var view = new WebView2 { Dock = DockStyle.Fill };
        Controls.Add(view);
        Shown += async (sender, args) =>
        {
            WatchReaderExit();
            try
            {
                var environment = await CoreWebView2Environment.CreateAsync(null, profile);
                if (IsDisposed) return;
                await view.EnsureCoreWebView2Async(environment);
                if (IsDisposed) return;
                view.CoreWebView2.DocumentTitleChanged += (s, e) => Text = view.CoreWebView2.DocumentTitle;
                view.CoreWebView2.WindowCloseRequested += (s, e) => Close();
                view.CoreWebView2.Navigate(url);
            }
            catch (Exception error)
            {
                if (IsDisposed) return;
                Environment.ExitCode = 1;
                MessageBox.Show(this, "無法啟動閱讀視窗。請確認已安裝 Microsoft Edge WebView2 Runtime。\n" + error.Message,
                                "CHM 閱讀器", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        };
    }

    private async void WatchReaderExit()
    {
        // Python 結束或要求關閉時會關閉管線；回到 UI 執行緒關閉本視窗。
        await Task.Run(() => Console.OpenStandardInput().ReadByte());
        if (!IsDisposed) Close();
    }
}
