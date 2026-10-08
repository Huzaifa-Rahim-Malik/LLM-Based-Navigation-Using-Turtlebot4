#!/bin/bash

# Installation script for TurtleBot Navigation Assistant - Voice Edition
# For Ubuntu 24

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  TurtleBot Navigation Assistant - Voice Setup                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if running on Ubuntu
if ! grep -q "Ubuntu" /etc/os-release; then
    echo "⚠️  Warning: This script is designed for Ubuntu 24"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "📦 Step 1: Installing system dependencies..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sudo apt-get update

# Audio libraries
sudo apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    espeak \
    espeak-ng \
    ffmpeg \
    libsndfile1 \
    pulseaudio \
    alsa-utils \
    python3-pip

if [ $? -eq 0 ]; then
    echo "✅ System dependencies installed successfully"
else
    echo "❌ Failed to install system dependencies"
    exit 1
fi

echo ""
echo "🐍 Step 2: Installing Python dependencies..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Install Python packages
pip install --break-system-packages openai-whisper sounddevice scipy numpy pyttsx3 noisereduce 2>&1 | grep -v "already satisfied"

if [ $? -eq 0 ]; then
    echo "✅ Python dependencies installed successfully"
else
    echo "❌ Failed to install Python dependencies"
    exit 1
fi

echo ""
echo "🎤 Step 3: Testing microphone..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# List audio devices
echo "Available recording devices:"
arecord -l | grep "card"

echo ""
echo "Testing microphone (5 second recording)..."
echo "Speak now: 'Testing one two three'"
arecord -d 5 -f cd /tmp/test_mic.wav 2>&1 | tail -1

if [ -f /tmp/test_mic.wav ]; then
    echo "✅ Microphone recording successful"
    echo "Playing back..."
    aplay /tmp/test_mic.wav 2>&1 | tail -1
    rm /tmp/test_mic.wav
else
    echo "❌ Microphone test failed"
    echo "   Check 'arecord -l' for available devices"
fi

echo ""
echo "🔊 Step 4: Testing text-to-speech..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

espeak "Text to speech is working correctly" 2>&1 | tail -1

if [ $? -eq 0 ]; then
    echo "✅ Text-to-speech working"
else
    echo "❌ Text-to-speech test failed"
fi

echo ""
echo "🧪 Step 5: Testing Whisper model download..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 -c "import whisper; print('Downloading base model...'); model = whisper.load_model('base'); print('✅ Whisper model loaded successfully')"

if [ $? -eq 0 ]; then
    echo "✅ Whisper ready"
else
    echo "❌ Whisper installation failed"
    exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  ✅ Installation Complete!                                     ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║  Quick Start:                                                  ║"
echo "║    1. Run: python3 main_voice.py                              ║"
echo "║    2. Type: 'voice mode' to enable voice                      ║"
echo "║    3. Speak your command after the 🎤 indicator               ║"
echo "║                                                                ║"
echo "║  Documentation: See VOICE_SETUP_GUIDE.md                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Optional: Bluetooth setup
read -p "Do you want to set up Bluetooth audio? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "📡 Setting up Bluetooth..."
    sudo apt-get install -y pulseaudio-module-bluetooth bluez
    echo ""
    echo "Run 'bluetoothctl' to pair your device:"
    echo "  > power on"
    echo "  > agent on"
    echo "  > scan on"
    echo "  > pair [MAC_ADDRESS]"
    echo "  > connect [MAC_ADDRESS]"
    echo "  > trust [MAC_ADDRESS]"
fi

echo ""
echo "Setup complete! 🎉"
