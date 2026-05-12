import re
import json

log_file = 'd:/kheilan/aisprint-keheilan/full_execution.log'
out_file = 'd:/kheilan/aisprint-keheilan/user_friendly_flow.md'

with open(log_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

log_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (DEBUG|INFO|WARNING|ERROR) ([a-zA-Z0-9_\.]+): (.*)')

steps = []
current_step = None

for line in lines:
    match = log_pattern.match(line)
    if match:
        timestamp, level, module, message = match.groups()
        
        if 'LLM Chat Request' in message:
            current_step = {'type': 'LLM Request', 'content': []}
            steps.append(current_step)
        elif 'LLM Chat Response' in message:
            current_step = {'type': 'LLM Response', 'content': []}
            steps.append(current_step)
        elif 'Tavily search request' in message:
            steps.append({'type': 'Web Search Request', 'content': [message.replace('Tavily search request: ', '')]})
            current_step = None
        elif 'Tavily search response' in message:
            steps.append({'type': 'Web Search Response', 'content': [message.replace('Tavily search response: ', '')]})
            current_step = None
        elif 'SoilGrids query request' in message:
            steps.append({'type': 'Soil API Request', 'content': [message.replace('SoilGrids query request: ', '')]})
            current_step = None
        elif 'SoilGrids query response' in message:
            steps.append({'type': 'Soil API Response', 'content': [message.replace('SoilGrids query response: ', '')]})
            current_step = None
        elif 'NASA POWER query request' in message:
            steps.append({'type': 'Weather API Request', 'content': [message.replace('NASA POWER query request: ', '')]})
            current_step = None
        elif 'NASA POWER query response' in message:
            steps.append({'type': 'Weather API Response', 'content': [message.replace('NASA POWER query response: ', '')]})
            current_step = None
        else:
            current_step = None
    else:
        if current_step is not None:
            current_step['content'].append(line)

with open(out_file, 'w', encoding='utf-8') as f:
    f.write('# Crop Agent Execution Flow\n\n')
    
    for i, step in enumerate(steps):
        f.write(f"### Step {i+1}: {step['type']}\n")
        
        content_str = ''.join(step['content']).strip()
        
        if step['type'] in ['Web Search Request', 'Soil API Request', 'Weather API Request']:
            try:
                # Format JSON if possible
                parsed = eval(content_str)
                formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                f.write(f"`json\n{formatted}\n`\n\n")
            except:
                f.write(f"`	ext\n{content_str}\n`\n\n")
        elif step['type'] in ['Web Search Response', 'Soil API Response', 'Weather API Response']:
            try:
                parsed = eval(content_str)
                if step['type'] == 'Web Search Response':
                    # Simplify tavily output
                    results = parsed.get('results', [])
                    for r in results:
                        f.write(f"- **URL:** {r.get('url')}\n  **Title:** {r.get('title')}\n")
                else:
                    formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                    f.write(f"`json\n{formatted[:1000]}... (truncated)\n`\n\n")
            except:
                f.write(f"`	ext\n{content_str[:1000]}... (truncated)\n`\n\n")
        else:
            if step['type'] == 'LLM Response' and content_str.startswith('{') or content_str.startswith('['):
                try:
                    parsed = json.loads(content_str)
                    formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
                    f.write(f"`json\n{formatted}\n`\n\n")
                except:
                    f.write(f"`	ext\n{content_str}\n`\n\n")
            else:
                f.write(f"`	ext\n{content_str}\n`\n\n")

print('Done')
