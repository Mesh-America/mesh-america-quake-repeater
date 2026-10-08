# Generate the two fixed phrases with Windows' local speech synthesizer.
# Requires ffmpeg and Python; outputs WAV previews plus the checked-in header.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateNotNullOrEmpty()]
    [string]$OutputDirectory = 'out/gps-voice',
    [ValidateNotNullOrEmpty()]
    [string]$OutputHeader = 'src/helpers/ui/GpsVoiceData.h',
    [ValidateNotNullOrEmpty()]
    [string]$Voice = 'Microsoft Zira Desktop',
    [ValidateRange(-10, 10)]
    [int]$Rate = -1,
    [switch]$Compress = $true,
    [ValidateRange(0.0625, 1.0)]
    [double]$PeakLimit = 0.12
)
$ErrorActionPreference = 'Stop'

# Require a deliberate header target for acoustic experiments. A normal run
# regenerates the selected Zira / rate -1 / compressed / gain-8 profile.
# Speech is prerecorded and shared by supported boards; no runtime TTS is needed.
# Original Zira: -Voice 'Microsoft Zira Desktop' -Compress:$false -PeakLimit 0.8
# with an explicit -OutputHeader.
if (-not $PSBoundParameters.ContainsKey('OutputHeader') -and
        ($Voice -ne 'Microsoft Zira Desktop' -or $Rate -ne -1 -or
         -not $Compress -or $PeakLimit -ne 0.12)) {
    throw 'Voice variants require an explicit -OutputHeader (use an out/gps-voice path for tests).'
}
$gpsDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$gpsHeader = [IO.Path]::GetFullPath($OutputHeader)
if ([IO.Path]::GetExtension($gpsHeader) -ine '.h') {
    throw '-OutputHeader must name a .h file.'
}
if (Test-Path -LiteralPath $gpsDirectory -PathType Leaf) {
    throw '-OutputDirectory names an existing file.'
}
if (Test-Path -LiteralPath $gpsHeader -PathType Container) {
    throw '-OutputHeader names an existing directory.'
}
$gpsEncoder = Join-Path $PSScriptRoot 'generate_gps_voice.py'
if (-not (Test-Path -LiteralPath $gpsEncoder -PathType Leaf)) {
    throw "Voice encoder not found: $gpsEncoder"
}

$gpsFilter = 'highpass=f=350,lowpass=f=3400,silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse'
if ($Compress) {
    # Raise quieter consonants without simply clipping the louder vowels.
    $gpsFilter += ',acompressor=threshold=0.08:ratio=6:attack=5:release=70:makeup=4:knee=4:detection=rms'
}
$gpsFilter += ',volume=1.4'
if ($Compress -or $PeakLimit -ne 0.8) {
    # Limit after resampling so the experimental PCM peak has real headroom.
    $gpsFilter += ',aresample=8000'
}
$gpsPeak = $PeakLimit.ToString('0.####', [Globalization.CultureInfo]::InvariantCulture)
$gpsFilter += ",alimiter=limit=${gpsPeak}:level=disabled,apad=pad_dur=0.05"
# For player gains 4 / 6 / 8, begin at -PeakLimit 0.18 / 0.12 / 0.09
# (72% nominal full scale after gain). Check decoded/reconstructed peaks too:
# ADPCM quantization and interpolation can overshoot the source PCM ceiling.
Write-Verbose "Voice: $Voice; rate: $Rate; output directory: $gpsDirectory"
Write-Verbose "Output header: $gpsHeader"
Write-Verbose "FFmpeg filter: $gpsFilter"
if (-not $PSCmdlet.ShouldProcess($gpsHeader, "Synthesize GPS on/off with $Voice and encode previews from $gpsDirectory")) {
    return
}

Add-Type -AssemblyName System.Speech
$gpsVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $gpsVoices = @($gpsVoice.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name })
    if ($gpsVoices -notcontains $Voice) {
        throw "Voice '$Voice' is unavailable. Installed voices: $($gpsVoices -join ', ')"
    }
    $gpsVoice.SelectVoice($Voice)
    $gpsVoice.Rate = $Rate
    Get-Command ffmpeg, python -ErrorAction Stop | Out-Null
    New-Item -ItemType Directory -Force -Path $gpsDirectory | Out-Null
    New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($gpsHeader)) | Out-Null
    foreach ($gpsState in @('on','off')) {
        $gpsRaw = Join-Path $gpsDirectory "gps-$gpsState-raw.wav"
        $gpsPcm = Join-Path $gpsDirectory "gps-$gpsState.wav"
        $gpsVoice.SetOutputToWaveFile([IO.Path]::GetFullPath($gpsRaw))
        $gpsVoice.Speak("G P S $gpsState")
        $gpsVoice.SetOutputToNull()
        # Keep enough consonant energy for a small beeper; limit clipping.
        & ffmpeg -hide_banner -loglevel error -y -i $gpsRaw -af $gpsFilter -ar 8000 -ac 1 -c:a pcm_s16le $gpsPcm
        if ($LASTEXITCODE -ne 0) { throw 'Voice conversion failed' }
    }
} finally { $gpsVoice.Dispose() }
& python $gpsEncoder --on (Join-Path $gpsDirectory 'gps-on.wav') --off (Join-Path $gpsDirectory 'gps-off.wav') --output $gpsHeader --voice $Voice
if ($LASTEXITCODE -ne 0) { throw 'Voice encoding failed' }
