# Reproduce the selected Zira / compressed button recordings for supported
# Full Companions; playback gain is configured by the firmware.
# GPS direction phrases are generated separately by generate_gps_voice.ps1.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateNotNullOrEmpty()]
    [string]$OutputDirectory = 'out/gps-voice/button-zira',
    [ValidateNotNullOrEmpty()]
    [string]$OutputHeader = 'src/helpers/ui/ButtonVoiceData.h',
    [ValidateNotNullOrEmpty()]
    [string]$Voice = 'Microsoft Zira Desktop',
    # Reuse original, already selected clips while adding a new catalog entry.
    [switch]$OnlyMissing
)
$ErrorActionPreference = 'Stop'
# Diagnostic voices must name a deliberate header target; the default stays
# the selected Zira / rate -1 / compressed / peak-0.12 profile.
if (-not $PSBoundParameters.ContainsKey('OutputHeader') -and
        $Voice -ne 'Microsoft Zira Desktop') {
    throw 'Voice variants require an explicit -OutputHeader (use an out/gps-voice path for tests).'
}
$buttonDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$buttonHeader = [IO.Path]::GetFullPath($OutputHeader)
if ([IO.Path]::GetExtension($buttonHeader) -ine '.h') {
    throw '-OutputHeader must name a .h file.'
}
if (Test-Path -LiteralPath $buttonDirectory -PathType Leaf) {
    throw '-OutputDirectory names an existing file.'
}
if (Test-Path -LiteralPath $buttonHeader -PathType Container) {
    throw '-OutputHeader names an existing directory.'
}
$buttonEncoder = Join-Path $PSScriptRoot 'generate_button_voice.py'
if (-not (Test-Path -LiteralPath $buttonEncoder -PathType Leaf)) {
    throw "Voice encoder not found: $buttonEncoder"
}
if (-not $PSCmdlet.ShouldProcess($buttonHeader, "Synthesize and encode $Voice button confirmations")) {
    return
}

$buttonPhrases = [ordered]@{
    ready = 'Ready'
    notificationCleared = 'Notification cleared'
    advertQueued = 'Advert queued'
    advertFailed = 'Advert failed'
    soundOn = 'Sound on'
    soundOff = 'Sound off'
    actionFailed = 'Action failed'
    usbSetup = 'USB setup'
    shuttingDown = 'Shutting down'
    restarting = 'Restarting'
    alertsSoundVibration = 'Sound and vibration'
    alertsSoundOnly = 'Sound only'
    alertsVibrationOnly = 'Vibration only'
    alertsSilent = 'Silent'
}
$buttonFilter = 'highpass=f=350,lowpass=f=3400,silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,acompressor=threshold=0.08:ratio=6:attack=5:release=70:makeup=4:knee=4:detection=rms,volume=1.4,aresample=8000,alimiter=limit=0.12:level=disabled,apad=pad_dur=0.05'
Add-Type -AssemblyName System.Speech
$buttonVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $buttonVoices = @($buttonVoice.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name })
    if ($buttonVoices -notcontains $Voice) {
        throw "Voice '$Voice' is unavailable. Installed voices: $($buttonVoices -join ', ')"
    }
    Get-Command ffmpeg, python -ErrorAction Stop | Out-Null
    $buttonVoice.SelectVoice($Voice)
    $buttonVoice.Rate = -1
    New-Item -ItemType Directory -Force -Path $buttonDirectory | Out-Null
    New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($buttonHeader)) | Out-Null
    foreach ($buttonName in $buttonPhrases.Keys) {
        $buttonRaw = Join-Path $buttonDirectory "$buttonName-raw.wav"
        $buttonPcm = Join-Path $buttonDirectory "$buttonName.wav"
        if ($OnlyMissing -and (Test-Path -LiteralPath $buttonPcm -PathType Leaf)) {
            continue
        }
        $buttonVoice.SetOutputToWaveFile($buttonRaw)
        $buttonVoice.Speak($buttonPhrases[$buttonName])
        $buttonVoice.SetOutputToNull()
        & ffmpeg -hide_banner -loglevel error -y -i $buttonRaw -af $buttonFilter -ar 8000 -ac 1 -c:a pcm_s16le $buttonPcm
        if ($LASTEXITCODE -ne 0) { throw "Voice conversion failed: $buttonName" }
    }
} finally { $buttonVoice.Dispose() }
& python $buttonEncoder --directory $buttonDirectory --output $buttonHeader --voice $Voice
if ($LASTEXITCODE -ne 0) { throw 'Button voice encoding failed' }
