param([string]$Payload)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function Get-ControlState($element, $action) {
    switch ($action) {
        'toggle' { return $element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Current.ToggleState.ToString() }
        'select' { return $element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected.ToString() }
        'expand' { return $element.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Current.ExpandCollapseState.ToString() }
        default { return '' }
    }
}
function Invoke-ControlAction($element, $action, $expected) {
    $before = Get-ControlState $element $action
    if ($before -cne $expected) { throw '控件状态已变化，请重新读取并圈出目标。' }
    if (($action -eq 'select' -and $before -eq 'True') -or ($action -eq 'expand' -and $before -eq 'Expanded')) {
        return @{ok=$true;executed=$false;verified=$true;status='already_satisfied';action=$action;before=$before;after=$before;message='目标已经处于所需状态，没有重复操作。'}
    }
    switch ($action) {
        'toggle' { $element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern).Toggle() }
        'select' { $element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() }
        'expand' { $element.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand() }
        'invoke' { $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
        default { throw '当前控件只支持定位。' }
    }
    if ($action -eq 'invoke') {
        return @{ok=$true;executed=$true;verified=$false;status='sent';action=$action;message='已发送这一次操作，尚未验证完成。请检查窗口中的实际结果。'}
    }
    $verified = $false
    $after = $null
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        try {
            $after = Get-ControlState $element $action
            $verified = ($action -eq 'toggle' -and $after -ne $before) -or ($action -eq 'select' -and $after -eq 'True') -or ($action -eq 'expand' -and $after -eq 'Expanded')
            if ($verified) { break }
        } catch { break }
        Start-Sleep -Milliseconds 100
    }
    $message = '操作已发送，但尚未确认状态变化。请检查当前窗口，不要重复点击。'
    $status = 'unverified'
    if ($verified) { $message = "已确认控件状态：$before → $after。请对照本步完成标准。"; $status = 'verified' }
    return @{ok=$verified;executed=$true;verified=$verified;status=$status;action=$action;before=$before;after=$after;message=$message}
}
try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Payload)) | ConvertFrom-Json
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$data.window.hwnd)
    if ($root.Current.ProcessId -ne $data.window.pid -or $root.Current.Name -ne $data.window.title) { throw '窗口已变化，请重新选择。' }
    $started = (Get-Process -Id $data.window.pid).StartTime.ToUniversalTime()
    $epoch = [DateTime]::SpecifyKind([datetime]'1970-01-01', [DateTimeKind]::Utc)
    if ([Math]::Abs(($started - $epoch).TotalSeconds - $data.window.started) -gt 0.1) { throw '窗口进程已变化。' }
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $script:items = New-Object System.Collections.ArrayList
    $script:elements = @{}
    $script:remaining = 500
    function Walk($element, $depth) {
        if ($depth -gt 8 -or $script:remaining -le 0) { return }
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child -and $script:remaining -gt 0) {
            $script:remaining--
            try {
                $current = $child.Current
                if (-not $current.IsPassword -and -not $current.IsOffscreen -and $current.IsEnabled) {
                    $rect = $current.BoundingRectangle
                    $type = $current.ControlType.ProgrammaticName -replace 'ControlType\.', ''
                    if ($rect.Width -gt 0 -and $rect.Height -gt 0 -and $type -in @('Button','CheckBox','RadioButton','TabItem','TreeItem','ComboBox','Edit','MenuItem','Hyperlink')) {
                        $key = $child.GetRuntimeId() -join '.'
                        $name = $current.Name
                        if ($type -eq 'Edit') { $name = $current.AutomationId; if (-not $name) { $name = '输入区域' } }
                        $action = ''
                        $pattern = $null
                        if ($child.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { $action = 'toggle' }
                        elseif ($child.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$pattern)) { $action = 'select' }
                        elseif ($child.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$pattern)) { $action = 'expand' }
                        elseif ($child.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $action = 'invoke' }
                        if ($name) {
                            $state = Get-ControlState $child $action
                            [void]$script:items.Add([pscustomobject]@{key=$key;name=$name;type=$type;action=$action;state=$state;automation_id=$current.AutomationId;class_name=$current.ClassName})
                            $script:elements[$key] = $child
                        }
                    }
                    Walk $child ($depth+1)
                }
            } catch {}
            $child = $walker.GetNextSibling($child)
        }
    }
    Walk $root 0
    if ($data.mode -eq 'observe') { @{items=@($script:items);truncated=($script:remaining -le 0)} | ConvertTo-Json -Depth 5 -Compress; exit }
    $age = ([DateTime]::UtcNow - $epoch).TotalSeconds - $data.item.observed_at
    if ($null -eq $data.item.observed_at -or $age -lt 0 -or $age -gt 180) { throw '控件列表已过期，请重新读取并圈出目标。' }
    $target = $script:elements[$data.item.key]
    $item = @($script:items | Where-Object { $_.key -eq $data.item.key })
    if ($null -eq $target -or $item.Count -ne 1) { throw '控件已变化，请重新定位。' }
    foreach ($field in @('name','type','action','automation_id','class_name','state')) {
        if ($item[0].$field -cne $data.item.$field) { throw '控件或状态已变化，请重新读取并圈出目标。' }
    }
    if ($data.mode -eq 'resolve') { '{"ok":true}'; exit }
    if ($data.mode -eq 'operate') {
        if ($target.Current.IsOffscreen -or -not $target.Current.IsEnabled -or $target.Current.IsPassword) { throw '控件当前不可操作，请重新定位。' }
        if ((Get-ControlState $target $data.item.action) -cne $data.item.state) { throw '控件状态已变化，请重新读取并圈出目标。' }
        Invoke-ControlAction $target $data.item.action $data.item.state | ConvertTo-Json -Compress; exit
    }
    if ($data.mode -ne 'highlight') { throw '无效操作。' }
    Add-Type -AssemblyName PresentationFramework
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName WindowsBase
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class LessonOverlay {
 [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int n);
 [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr h, int n, int v);
}
'@
    $overlay = New-Object Windows.Window
    $overlay.WindowStyle = 'None'
    $overlay.AllowsTransparency = $true
    $overlay.Background = [Windows.Media.Brushes]::Transparent
    $overlay.Topmost = $true
    $overlay.ShowInTaskbar = $false
    $overlay.ShowActivated = $false
    $overlay.IsHitTestVisible = $false
    $ellipse = New-Object Windows.Shapes.Ellipse
    $ellipse.Stroke = [Windows.Media.BrushConverter]::new().ConvertFromString('#10BDE0')
    $ellipse.StrokeThickness = 4
    $ellipse.Margin = '8'
    $glow = New-Object Windows.Media.Effects.DropShadowEffect
    $glow.Color = [Windows.Media.Colors]::DeepSkyBlue
    $glow.BlurRadius = 14
    $glow.ShadowDepth = 0
    $ellipse.Effect = $glow
    $overlay.Content = $ellipse
    $overlay.Add_SourceInitialized({
        $handle = [Windows.Interop.WindowInteropHelper]::new($overlay).Handle
        $style = [LessonOverlay]::GetWindowLong($handle, -20)
        [void][LessonOverlay]::SetWindowLong($handle, -20, ($style -bor 0x20 -bor 0x08000000 -bor 0x80))
    })
    $timer = New-Object Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromMilliseconds(100)
    $until = [DateTime]::UtcNow.AddSeconds(6)
    $script:highlightReady = $false
    $timer.Add_Tick({
        try {
            if ([DateTime]::UtcNow -gt $until -or $target.Current.IsOffscreen -or -not $target.Current.IsEnabled -or $root.Current.Name -ne $data.window.title) { $overlay.Close(); return }
            if ($target.Current.AutomationId -cne $data.item.automation_id -or $target.Current.ClassName -cne $data.item.class_name -or (Get-ControlState $target $data.item.action) -cne $data.item.state) { $overlay.Close(); return }
            $rect = $target.Current.BoundingRectangle
            if ($rect.Width -le 0 -or $rect.Height -le 0) { $overlay.Close(); return }
            $source = [Windows.PresentationSource]::FromVisual($overlay)
            $matrix = $source.CompositionTarget.TransformFromDevice
            $point = $matrix.Transform([Windows.Point]::new($rect.X-16,$rect.Y-16))
            $overlay.Left = $point.X; $overlay.Top = $point.Y
            $overlay.Width = ($rect.Width+32)*$matrix.M11; $overlay.Height = ($rect.Height+32)*$matrix.M22
            if (-not $script:highlightReady) { $script:highlightReady=$true; [Console]::Out.WriteLine('READY'); [Console]::Out.Flush() }
        } catch { $overlay.Close() }
    })
    $overlay.Width = 1; $overlay.Height = 1
    $overlay.Add_Closed({ $timer.Stop() })
    $timer.Start()
    [void]$overlay.ShowDialog()
} catch {
    @{error=$_.Exception.Message} | ConvertTo-Json -Compress
    exit 1
}
