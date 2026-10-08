#!/bin/bash

# Piper TTS Installation Script
# Automates installation of Piper and voice models for natural TTS

set -e  # Exit on error

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          PIPER TTS INSTALLATION SCRIPT                         ║"
echo "║          Natural Voice for TurtleBot Assistant                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
    echo -e "${RED}Please do not run as root (no sudo needed for most steps)${NC}"
    exit 1
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Step 1: Check for existing installation
echo "Step 1: Checking for existing Piper installation..."
if command_exists piper; then
    echo -e "${GREEN}✓ Piper already installed!${NC}"
    piper --version
    PIPER_INSTALLED=true
else
    echo -e "${YELLOW}⚠ Piper not found${NC}"
    PIPER_INSTALLED=false
fi
echo ""

# Step 2: Install Piper
if [ "$PIPER_INSTALLED" = false ]; then
    echo "Step 2: Installing Piper..."
    echo ""
    echo "Choose installation method:"
    echo "  1) APT package (easiest, Ubuntu/Debian)"
    echo "  2) Download pre-built binary (manual)"
    echo "  3) Skip Piper installation"
    echo ""
    read -p "Select option (1-3): " install_method
    
    case $install_method in
        1)
            echo "Installing via APT..."
            sudo apt update
            sudo apt install -y piper-tts
            
            if command_exists piper; then
                echo -e "${GREEN}✓ Piper installed successfully via APT!${NC}"
            else
                echo -e "${RED}✗ APT installation failed${NC}"
                echo "Try method 2 (manual download)"
                exit 1
            fi
            ;;
        
        2)
            echo "Downloading pre-built binary..."
            
            # Detect architecture
            ARCH=$(uname -m)
            if [ "$ARCH" = "x86_64" ]; then
                PIPER_URL="https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz"
            elif [ "$ARCH" = "aarch64" ]; then
                PIPER_URL="https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz"
            else
                echo -e "${RED}✗ Unsupported architecture: $ARCH${NC}"
                exit 1
            fi
            
            # Download and install
            cd /tmp
            wget -q --show-progress "$PIPER_URL" -O piper.tar.gz
            tar xzf piper.tar.gz
            
            # Install to /usr/local/bin (requires sudo)
            echo "Installing Piper to /usr/local/bin (requires sudo)..."
            sudo mv piper/piper /usr/local/bin/
            sudo chmod +x /usr/local/bin/piper
            
            # Cleanup
            rm -rf piper piper.tar.gz
            
            if command_exists piper; then
                echo -e "${GREEN}✓ Piper installed successfully!${NC}"
            else
                echo -e "${RED}✗ Installation failed${NC}"
                exit 1
            fi
            ;;
        
        3)
            echo "Skipping Piper installation"
            ;;
        
        *)
            echo -e "${RED}Invalid option${NC}"
            exit 1
            ;;
    esac
else
    echo "Step 2: Skipping (Piper already installed)"
fi
echo ""

# Step 3: Download voice models
echo "Step 3: Downloading voice models..."

# Create model directory
MODEL_DIR="$HOME/piper/models"
mkdir -p "$MODEL_DIR"

echo "Available voices:"
echo "  1) en_US-lessac-medium (Female, natural - RECOMMENDED)"
echo "  2) en_GB-northern_english_male-medium (Male, clear)"
echo "  3) en_US-lessac-high (Female, highest quality - slower)"
echo "  4) Download all three"
echo "  5) Skip model download"
echo ""
read -p "Select option (1-5): " model_choice

BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

download_model() {
    local model_path=$1
    local model_name=$2
    
    echo "Downloading $model_name..."
    
    # Download .onnx file
    wget -q --show-progress "${BASE_URL}/${model_path}.onnx" -O "${MODEL_DIR}/${model_name}.onnx"
    
    # Download .onnx.json file
    wget -q --show-progress "${BASE_URL}/${model_path}.onnx.json" -O "${MODEL_DIR}/${model_name}.onnx.json"
    
    if [ -f "${MODEL_DIR}/${model_name}.onnx" ] && [ -f "${MODEL_DIR}/${model_name}.onnx.json" ]; then
        echo -e "${GREEN}✓ ${model_name} downloaded successfully${NC}"
        return 0
    else
        echo -e "${RED}✗ Download failed for ${model_name}${NC}"
        return 1
    fi
}

case $model_choice in
    1)
        download_model "en/en_US/lessac/medium/en_US-lessac-medium" "en_US-lessac-medium"
        ;;
    2)
        download_model "en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium" "en_GB-northern_english_male-medium"
        ;;
    3)
        download_model "en/en_US/lessac/high/en_US-lessac-high" "en_US-lessac-high"
        ;;
    4)
        download_model "en/en_US/lessac/medium/en_US-lessac-medium" "en_US-lessac-medium"
        download_model "en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium" "en_GB-northern_english_male-medium"
        download_model "en/en_US/lessac/high/en_US-lessac-high" "en_US-lessac-high"
        ;;
    5)
        echo "Skipping model download"
        ;;
    *)
        echo -e "${RED}Invalid option${NC}"
        exit 1
        ;;
esac
echo ""

# Step 4: Test installation
echo "Step 4: Testing Piper installation..."

if command_exists piper; then
    # Find a model to test with
    MODEL_FILE=$(find "$MODEL_DIR" -name "*.onnx" -type f | head -n 1)
    
    if [ -n "$MODEL_FILE" ]; then
        CONFIG_FILE="${MODEL_FILE}.json"
        
        echo "Testing with model: $(basename $MODEL_FILE)"
        echo "Generating test audio..."
        
        echo "Hello! This is a test of Piper text to speech. If you can hear this, Piper is working correctly!" | \
            piper --model "$MODEL_FILE" --config "$CONFIG_FILE" --output_file /tmp/piper_test.wav
        
        if [ -f /tmp/piper_test.wav ]; then
            echo "Playing test audio..."
            
            if command_exists aplay; then
                aplay /tmp/piper_test.wav
            elif command_exists paplay; then
                paplay /tmp/piper_test.wav
            else
                echo -e "${YELLOW}⚠ No audio player found (aplay/paplay)${NC}"
                echo "Install with: sudo apt install alsa-utils pulseaudio-utils"
            fi
            
            rm /tmp/piper_test.wav
            echo -e "${GREEN}✓ Test successful!${NC}"
        else
            echo -e "${RED}✗ Test failed - audio file not generated${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ No model found in $MODEL_DIR${NC}"
        echo "Download a model (see README)"
    fi
else
    echo -e "${RED}✗ Piper not found${NC}"
fi
echo ""

# Step 5: Summary
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    INSTALLATION SUMMARY                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

if command_exists piper; then
    echo -e "${GREEN}✓ Piper TTS: INSTALLED${NC}"
    piper --version
else
    echo -e "${RED}✗ Piper TTS: NOT INSTALLED${NC}"
fi
echo ""

MODEL_COUNT=$(find "$MODEL_DIR" -name "*.onnx" -type f 2>/dev/null | wc -l)
if [ "$MODEL_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Voice Models: $MODEL_COUNT installed${NC}"
    echo "   Location: $MODEL_DIR"
    echo "   Models:"
    find "$MODEL_DIR" -name "*.onnx" -type f -exec basename {} .onnx \;
else
    echo -e "${YELLOW}⚠ Voice Models: NONE${NC}"
    echo "   Download models manually (see README)"
fi
echo ""

# Step 6: Next steps
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                        NEXT STEPS                              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "1. Copy the fixed files to your project:"
echo "   cp chat_interface.py ~/turtlebot4/turtlebot4_ws/turtlebot4_nav_text/src/"
echo "   cp voice_output.py ~/turtlebot4/turtlebot4_ws/turtlebot4_nav_text/src/"
echo ""
echo "2. Edit main.py to use Piper:"
echo "   Change engine_type=\"pyttsx3\" to engine_type=\"piper\""
echo ""
echo "3. Run your robot:"
echo "   cd ~/turtlebot4/turtlebot4_ws/turtlebot4_nav_text/src/"
echo "   ./main.py"
echo ""
echo "4. For more help, see README_FIXES.md"
echo ""
echo -e "${GREEN}Installation complete! Enjoy natural voice! 🎉${NC}"
