param(
    [string]$Title = "动手学桌面练习器",
    [string]$PolishPython = "",
    [string]$PolishScript = ""
)

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Width="580" Height="520" ResizeMode="NoResize" WindowStyle="None"
        AllowsTransparency="True" Background="Transparent"
        WindowStartupLocation="CenterScreen" FontFamily="Microsoft YaHei UI, Microsoft YaHei, Segoe UI"
        TextOptions.TextFormattingMode="Display" UseLayoutRounding="True">
    <Window.Resources>
        <Style TargetType="TextBlock">
            <Setter Property="Foreground" Value="#214958"/>
            <Setter Property="FontWeight" Value="Medium"/>
        </Style>
        <Style TargetType="Button" x:Key="ActionButton">
            <Setter Property="Height" Value="42"/>
            <Setter Property="FontSize" Value="14"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Background" Value="#0787A6"/>
            <Setter Property="Foreground" Value="White"/>
            <Setter Property="BorderBrush" Value="#0787A6"/>
            <Setter Property="Padding" Value="18,0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="Face" CornerRadius="10" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Face" Property="Opacity" Value="0.84"/></Trigger>
                            <Trigger Property="IsPressed" Value="True"><Setter TargetName="Face" Property="Opacity" Value="0.65"/></Trigger>
                            <Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="Face" Property="BorderBrush" Value="#19C0D8"/><Setter TargetName="Face" Property="BorderThickness" Value="2"/></Trigger>
                            <Trigger Property="IsEnabled" Value="False"><Setter TargetName="Face" Property="Opacity" Value="0.4"/></Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>
    <Border Margin="14" CornerRadius="20" Background="#FCFDFE" BorderBrush="#D7E6EC" BorderThickness="1">
        <Border.Effect><DropShadowEffect Color="#183F50" Opacity="0.17" BlurRadius="22" ShadowDepth="5"/></Border.Effect>
        <Grid Margin="28,20,28,24">
            <Grid.RowDefinitions>
                <RowDefinition Height="38"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <Grid>
                <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="32"/></Grid.ColumnDefinitions>
                <Border x:Name="TitleGrip" Background="Transparent" Cursor="SizeAll">
                    <StackPanel Orientation="Horizontal" VerticalAlignment="Top">
                        <Border CornerRadius="8" Background="#DFF5FA" Width="28" Height="28" Margin="0,0,9,0">
                            <TextBlock Text="✦" FontSize="18" Foreground="#0798B6" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <TextBlock Text="动手学" FontSize="15" FontWeight="Bold" VerticalAlignment="Center"/>
                        <TextBlock Text="桌面练习" FontSize="12" Foreground="#77909B" Margin="10,0,0,0" VerticalAlignment="Center"/>
                    </StackPanel>
                </Border>
                <Button x:Name="CloseButton" Grid.Column="1" Content="×" AutomationProperties.Name="关闭练习"
                        Style="{StaticResource ActionButton}" Height="28" Width="28" Padding="0" FontSize="20"
                        Background="#EEF4F6" BorderBrush="#EEF4F6" Foreground="#65818D" VerticalAlignment="Top"/>
            </Grid>
            <StackPanel Grid.Row="1">
                <TextBlock Text="把第一步，做出来。" FontSize="27" FontWeight="Bold" Margin="0,13,0,8"/>
                <TextBlock Text="写下一个目标，亲手完成检查与撤销。" FontSize="13" Foreground="#69818C" Margin="0,0,0,22"/>
                <Grid Margin="0,0,0,22">
                    <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition Width="22"/><ColumnDefinition/><ColumnDefinition Width="22"/><ColumnDefinition/></Grid.ColumnDefinitions>
                    <Border x:Name="StageOne" Background="#E4F5F9" CornerRadius="9" Padding="10,9"><TextBlock Text="01  写下目标" FontSize="12" FontWeight="SemiBold" Foreground="#137990" HorizontalAlignment="Center"/></Border>
                    <TextBlock Grid.Column="1" Text="›" Foreground="#B0C4CC" VerticalAlignment="Center" HorizontalAlignment="Center"/>
                    <Border x:Name="StageTwo" Grid.Column="2" Background="#F0F4F6" CornerRadius="9" Padding="10,9"><TextBlock Text="02  检查结果" FontSize="12" HorizontalAlignment="Center"/></Border>
                    <TextBlock Grid.Column="3" Text="›" Foreground="#B0C4CC" VerticalAlignment="Center" HorizontalAlignment="Center"/>
                    <Border x:Name="StageThree" Grid.Column="4" Background="#F0F4F6" CornerRadius="9" Padding="10,9"><TextBlock Text="03  试着撤销" FontSize="12" HorizontalAlignment="Center"/></Border>
                </Grid>
                <Grid Margin="0,0,0,8">
                    <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition Width="68"/></Grid.ColumnDefinitions>
                    <TextBlock Text="这次，你想完成什么？" FontSize="14" FontWeight="SemiBold" VerticalAlignment="Center"/>
                    <Button x:Name="PolishButton" Grid.Column="1" Content="润色" AutomationProperties.Name="润色目标" AutomationProperties.AutomationId="PolishGoal"
                            Style="{StaticResource ActionButton}" Height="28" FontSize="12" Padding="10,0"
                            Background="#E4F5F9" Foreground="#137990" BorderBrush="#CEEAF1" ToolTip="使用已配置的模型润色，预览后再采纳"/>
                </Grid>
                <Grid>
                    <TextBox x:Name="GoalInput" Height="64" FontSize="15" Padding="14,12" TextWrapping="Wrap" AcceptsReturn="True" VerticalScrollBarVisibility="Auto"
                             Foreground="#214958" Background="White" CaretBrush="#0787A6" BorderBrush="#CEDFE6"
                             AutomationProperties.Name="输入目标" AutomationProperties.AutomationId="GoalInput">
                        <TextBox.Template>
                            <ControlTemplate TargetType="TextBox">
                                <Border x:Name="InputFace" CornerRadius="11" BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1" Background="{TemplateBinding Background}">
                                    <ScrollViewer x:Name="PART_ContentHost" Margin="{TemplateBinding Padding}"/>
                                </Border>
                                <ControlTemplate.Triggers>
                                    <Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="InputFace" Property="BorderBrush" Value="#1BB7D1"/><Setter TargetName="InputFace" Property="BorderThickness" Value="1.5"/></Trigger>
                                </ControlTemplate.Triggers>
                            </ControlTemplate>
                        </TextBox.Template>
                    </TextBox>
                    <TextBlock x:Name="Placeholder" Text="例如：整理本周销售表，生成一份汇总" FontSize="13" Foreground="#8AA0AB" Margin="15,15,12,0" IsHitTestVisible="False"/>
                </Grid>
                <Border x:Name="PolishPanel" Visibility="Collapsed" CornerRadius="11" Background="#F0F8FA" BorderBrush="#D5E9EE" BorderThickness="1" Padding="12" Margin="0,10,0,0">
                    <StackPanel>
                        <TextBlock x:Name="PolishStatus" Text="正在润色…" FontSize="12" TextWrapping="Wrap" Foreground="#4D7583" Margin="0,0,0,8" AutomationProperties.AutomationId="PolishStatus"/>
                        <TextBox x:Name="PolishPreview" Visibility="Collapsed" IsReadOnly="True" TextWrapping="Wrap" AcceptsReturn="True" Height="80" VerticalScrollBarVisibility="Auto"
                                 FontSize="13" Padding="8" Background="White" Foreground="#214958" BorderBrush="#D5E9EE" AutomationProperties.Name="润色预览" AutomationProperties.AutomationId="PolishPreview"/>
                        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,9,0,0">
                            <Button x:Name="PolishAccept" Content="采纳" IsEnabled="False" Style="{StaticResource ActionButton}" Height="28" FontSize="12" Padding="16,0" AutomationProperties.Name="采纳润色" AutomationProperties.AutomationId="PolishAccept"/>
                            <Button x:Name="PolishCancel" Content="取消" Style="{StaticResource ActionButton}" Height="28" FontSize="12" Padding="16,0" Margin="8,0,0,0" Background="White" Foreground="#426372" BorderBrush="#D4E3E9" AutomationProperties.Name="取消润色" AutomationProperties.AutomationId="PolishCancel"/>
                        </StackPanel>
                    </StackPanel>
                </Border>
                <Grid Margin="0,14,0,20">
                    <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition Width="12"/><ColumnDefinition Width="120"/></Grid.ColumnDefinitions>
                    <Button x:Name="CheckButton" Content="检查这一步  →" AutomationProperties.Name="检查" Style="{StaticResource ActionButton}"/>
                    <Button x:Name="UndoButton" Grid.Column="2" Content="↶  撤销" AutomationProperties.Name="撤销" Style="{StaticResource ActionButton}" Background="White" Foreground="#426372" BorderBrush="#D4E3E9"/>
                </Grid>
            </StackPanel>
            <Border x:Name="StatusCard" Grid.Row="2" CornerRadius="12" Background="#F0F7F9" Padding="16,13">
                <Grid>
                    <Grid.ColumnDefinitions><ColumnDefinition Width="30"/><ColumnDefinition/></Grid.ColumnDefinitions>
                    <TextBlock x:Name="StatusIcon" Text="○" FontSize="22" Foreground="#47AFC3" VerticalAlignment="Center"/>
                    <StackPanel Grid.Column="1">
                        <TextBlock x:Name="StatusTitle" Text="按自己的节奏来" FontSize="13" FontWeight="SemiBold" Margin="0,0,0,4"/>
                        <TextBlock x:Name="StatusText" Text="等待输入" TextWrapping="Wrap" FontSize="12" Foreground="#698793" AutomationProperties.AutomationId="PracticeStatus"/>
                    </StackPanel>
                </Grid>
            </Border>
        </Grid>
    </Border>
</Window>
"@

$window = [System.Windows.Markup.XamlReader]::Parse($xaml)
$window.Title = $Title
$goalInput = $window.FindName("GoalInput")
$checkButton = $window.FindName("CheckButton")
$undoButton = $window.FindName("UndoButton")
$statusText = $window.FindName("StatusText")
$statusTitle = $window.FindName("StatusTitle")
$statusIcon = $window.FindName("StatusIcon")
$statusCard = $window.FindName("StatusCard")
$placeholder = $window.FindName("Placeholder")
$polishButton = $window.FindName("PolishButton")
$polishPanel = $window.FindName("PolishPanel")
$polishStatus = $window.FindName("PolishStatus")
$polishPreview = $window.FindName("PolishPreview")
$polishAccept = $window.FindName("PolishAccept")
$polishCancel = $window.FindName("PolishCancel")
$polishTimer = [Windows.Threading.DispatcherTimer]::new()
$polishTimer.Interval = [TimeSpan]::FromMilliseconds(150)
$polishState = @{ Process=$null; Stdout=$null; Stderr=$null; Stdin=$null; InputClosed=$false; Started=$null; Id=''; Original=''; Draft=''; Revision=0; RequestRevision=-1 }
$stages = @($window.FindName("StageOne"), $window.FindName("StageTwo"), $window.FindName("StageThree"))
$brushes = [Windows.Media.BrushConverter]::new()

function Set-Stage([int]$active) {
    for ($i=0; $i -lt $stages.Count; $i++) {
        $stages[$i].Background = $brushes.ConvertFromString($(if($i -eq $active){'#DFF4F9'}else{'#F0F4F6'}))
    }
}

function Stop-PolishWorker {
    $polishTimer.Stop()
    $child = $polishState.Process
    $polishState.Process = $null
    $polishState.Stdout = $null
    $polishState.Stderr = $null
    $polishState.Stdin = $null
    if ($null -ne $child) {
        try {
            if (-not $child.HasExited) {
                $stop = [Diagnostics.ProcessStartInfo]::new()
                $stop.FileName = [IO.Path]::Combine($env:SystemRoot, 'System32', 'taskkill.exe')
                $stop.Arguments = '/PID ' + ([int]$child.Id).ToString([Globalization.CultureInfo]::InvariantCulture) + ' /T /F'
                $stop.UseShellExecute = $false
                $stop.CreateNoWindow = $true
                $stop.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
                $stopper = [Diagnostics.Process]::Start($stop)
                if ($null -ne $stopper) { $stopper.Dispose() }
            }
        } catch {}
        try { $child.Dispose() } catch {}
    }
    $polishButton.IsEnabled = $true
}

function Show-PolishPanel {
    $polishPanel.Visibility = 'Visible'
    $window.Height = 710
    $area = [Windows.SystemParameters]::WorkArea
    if ($window.Top + $window.Height -gt $area.Bottom) {
        $window.Top = [Math]::Max($area.Top, $area.Bottom - $window.Height)
    }
}

function Close-PolishPanel {
    Stop-PolishWorker
    $polishState.Id = ''
    $polishState.Draft = ''
    $polishPanel.Visibility = 'Collapsed'
    $polishPreview.Visibility = 'Collapsed'
    $polishPreview.Text = ''
    $polishAccept.IsEnabled = $false
    $window.Height = 520
}

function Set-PolishError([string]$message) {
    Stop-PolishWorker
    $polishState.Draft = ''
    $polishAccept.IsEnabled = $false
    $polishPreview.Text = ''
    $polishPreview.Visibility = 'Collapsed'
    $polishStatus.Text = $message
}

$polishButton.Add_Click({
    Stop-PolishWorker
    Show-PolishPanel
    $polishAccept.IsEnabled = $false
    $polishPreview.Text = ''
    $polishPreview.Visibility = 'Collapsed'
    $polishState.Draft = ''
    if ([string]::IsNullOrWhiteSpace($goalInput.Text)) {
        Set-PolishError '先写下需要润色的目标。'
        [void]$goalInput.Focus()
        return
    }
    if ($goalInput.Text.Length -gt 12000) {
        Set-PolishError '文字较长，请缩短后再润色。'
        return
    }
    if ([string]::IsNullOrWhiteSpace($PolishPython) -or [string]::IsNullOrWhiteSpace($PolishScript) -or -not (Test-Path -LiteralPath $PolishPython -PathType Leaf) -or -not (Test-Path -LiteralPath $PolishScript -PathType Leaf)) {
        Set-PolishError '请从学习应用重新打开练习器，再试一次。'
        return
    }
    $polishState.Id = [Guid]::NewGuid().ToString('N')
    $polishState.Original = $goalInput.Text
    $polishState.RequestRevision = $polishState.Revision
    $polishStatus.Text = '正在润色，可随时取消。'
    try {
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $PolishPython
        $start.Arguments = '-I "' + $PolishScript + '"'
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardInput = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
        $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
        $child = [Diagnostics.Process]::new()
        $child.StartInfo = $start
        $polishState.Process = $child
        [void]$child.Start()
        $polishState.Stdout = $child.StandardOutput.ReadToEndAsync()
        $polishState.Stderr = $child.StandardError.ReadToEndAsync()
        $request = @{ id=$polishState.Id; text=$polishState.Original; kind='goal' } | ConvertTo-Json -Compress
        $bytes = [Text.Encoding]::UTF8.GetBytes($request)
        $polishState.Stdin = $child.StandardInput.BaseStream.WriteAsync($bytes, 0, $bytes.Length)
        $polishState.InputClosed = $false
        $polishState.Started = [DateTime]::UtcNow
        $polishButton.IsEnabled = $false
        $polishTimer.Start()
    } catch {
        Set-PolishError '暂时无法润色，请检查模型配置后重试。'
    }
})

$polishTimer.Add_Tick({
    $child = $polishState.Process
    if ($null -eq $child) { $polishTimer.Stop(); return }
    if (([DateTime]::UtcNow - $polishState.Started).TotalSeconds -gt 120) {
        Set-PolishError '这次等待较久，已停止润色，请稍后重试。'
        return
    }
    if ($polishState.RequestRevision -ne $polishState.Revision -or $goalInput.Text -cne $polishState.Original) {
        Set-PolishError '输入已修改，请重新润色。'
        return
    }
    try {
        if (-not $polishState.InputClosed) {
            if (-not $polishState.Stdin.IsCompleted) { return }
            [void]$polishState.Stdin.GetAwaiter().GetResult()
            $child.StandardInput.Close()
            $polishState.InputClosed = $true
        }
        if (-not $child.HasExited -or -not $polishState.Stdout.IsCompleted -or -not $polishState.Stderr.IsCompleted) { return }
        $output = $polishState.Stdout.GetAwaiter().GetResult()
        $responseLine = @($output -split "`r?`n" | Where-Object { $_.StartsWith('__LE_POLISH_RESULT__:') })
        if ($child.ExitCode -ne 0 -or $responseLine.Count -ne 1) { throw 'invalid response' }
        $response = $responseLine[0].Substring('__LE_POLISH_RESULT__:'.Length) | ConvertFrom-Json
        if ($response.id -cne $polishState.Id -or $response.ok -ne $true -or $response.text -isnot [string] -or [string]::IsNullOrWhiteSpace($response.text) -or $response.text.Length -gt 12000) { throw 'invalid response' }
        Stop-PolishWorker
        $polishState.Draft = $response.text
        $polishPreview.Text = $response.text
        $polishPreview.Visibility = 'Visible'
        if ($response.text -ceq $polishState.Original) {
            $polishStatus.Text = '原文已经简洁，可以保留。'
            $polishAccept.IsEnabled = $false
        } else {
            $polishStatus.Text = '先看预览，采纳后替换输入框。'
            $polishAccept.IsEnabled = $true
        }
    } catch {
        Set-PolishError '暂时无法润色，请检查模型配置后重试。'
    }
})

$polishAccept.Add_Click({
    if ($polishState.RequestRevision -ne $polishState.Revision -or $goalInput.Text -cne $polishState.Original -or [string]::IsNullOrWhiteSpace($polishState.Draft)) {
        Set-PolishError '输入已修改，请重新润色。'
        return
    }
    $draft = $polishState.Draft
    Close-PolishPanel
    $goalInput.Text = $draft
    $goalInput.CaretIndex = $goalInput.Text.Length
    [void]$goalInput.Focus()
})
$polishCancel.Add_Click({ Close-PolishPanel; [void]$goalInput.Focus() })
$window.Add_Closed({ Stop-PolishWorker })

$window.FindName("CloseButton").Add_Click({ $window.Close() })
$window.FindName("TitleGrip").Add_MouseLeftButtonDown({ $window.DragMove() })
$goalInput.Add_TextChanged({
    $polishState.Revision++
    if ($polishPanel.Visibility -eq 'Visible') { Set-PolishError '输入已修改，请重新润色。' }
    $placeholder.Visibility = $(if($goalInput.Text.Length -gt 0){'Collapsed'}else{'Visible'})
    $statusTitle.Text = '准备好就检查一下'
    $statusText.Text = $(if($goalInput.Text.Length -gt 0){'这里只练习输入与检查，不会执行你写下的任务。'}else{'等待输入'})
    $statusIcon.Text = '○'
    $statusCard.Background = $brushes.ConvertFromString('#F0F7F9')
    Set-Stage 0
})

$checkButton.Add_Click({
    if ([string]::IsNullOrWhiteSpace($goalInput.Text)) {
        $statusTitle.Text = "先写下一个小目标"
        $statusText.Text = "请先输入任务"
        $statusIcon.Text = '↗'
        [void]$goalInput.Focus()
    } else {
        $statusTitle.Text = "文字检查通过，试试撤销"
        $statusText.Text = "已完成：" + $goalInput.Text
        $statusIcon.Text = '✓'
        $statusCard.Background = $brushes.ConvertFromString('#E5F7FA')
        Set-Stage 1
    }
})

$undoButton.Add_Click({
    $goalInput.Clear()
    $statusTitle.Text = "放心，已经回到起点"
    $statusText.Text = "已撤销"
    $statusIcon.Text = '↶'
    $statusCard.Background = $brushes.ConvertFromString('#EDF3FA')
    Set-Stage 2
})

$window.Add_Loaded({
    [void]$goalInput.Focus()
    if ([Windows.SystemParameters]::ClientAreaAnimation) {
        $fade = [Windows.Media.Animation.DoubleAnimation]::new(0,1,[TimeSpan]::FromMilliseconds(180))
        $window.BeginAnimation([Windows.Window]::OpacityProperty,$fade)
    }
})

$window.ShowDialog() | Out-Null
