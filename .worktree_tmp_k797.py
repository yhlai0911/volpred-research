import json, sys
# Read the script content from stdin and write it
content = sys.stdin.read()
with open('/Users/yhlai0911/Desktop/volpred-research/experiments/k797_kan_garch.py', 'w') as f:
    f.write(content)
print("Written OK")
