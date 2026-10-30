# Charm VHS script for git-narrator demo GIF
# Run: vhs demo.tape

Output assets/demo.gif

Set FontSize 18
Set Width 1200
Set Height 680
Set WindowBar "Colorful"
Set WindowBarSize 40
Set Theme "Catppuccin Mocha"
Set FontFamily "JetBrains Mono"
Set Padding 20
Set Margin 10
Set CornerRadius 12
Set TypingSpeed 45ms

# Initial greeting and git status
Type "git status --short"
Sleep 400ms
Enter
Sleep 1.2s

# Run git narrator with instant auto-detection
Type "git narrator"
Sleep 300ms
Enter
Sleep 4s

# Switch to Risk Radar tab [2]
Type "2"
Sleep 2.5s

# Switch to Visual Flow tab [3]
Type "3"
Sleep 2.5s

# Switch to Commit & PR tab [4]
Type "4"
Sleep 2s

# Copy PR to clipboard
Type "p"
Sleep 1.5s
