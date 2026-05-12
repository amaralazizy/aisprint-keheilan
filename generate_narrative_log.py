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
        
        if 'LLM Chat Request:' in message:
            current_step = {'type': 'LLM Request', 'content': []}
            steps.append(current_step)
        elif 'LLM Chat Response:' in message:
            current_step = {'type': 'LLM Response', 'content': []}
            steps.append(current_step)
        elif 'Tavily search request:' in message:
            steps.append({'type': 'Web Search Request', 'content': [message.replace('Tavily search request: ', '')]})
            current_step = None
        elif 'Tavily search response:' in message:
            steps.append({'type': 'Web Search Response', 'content': [message.replace('Tavily search response: ', '')]})
            current_step = None
        elif 'SoilGrids query request:' in message:
            steps.append({'type': 'Soil API Request', 'content': [message.replace('SoilGrids query request: ', '')]})
            current_step = None
        elif 'SoilGrids query response:' in message:
            steps.append({'type': 'Soil API Response', 'content': [message.replace('SoilGrids query response: ', '')]})
            current_step = None
        elif 'NASA POWER query request:' in message:
            steps.append({'type': 'Weather API Request', 'content': [message.replace('NASA POWER query request: ', '')]})
            current_step = None
        elif 'NASA POWER query response:' in message:
            steps.append({'type': 'Weather API Response', 'content': [message.replace('NASA POWER query response: ', '')]})
            current_step = None
        else:
            current_step = None
    else:
        if current_step is not None:
            current_step['content'].append(line)

with open(out_file, 'w', encoding='utf-8') as f:
    f.write('# Crop Recommendation Execution Flow\n\n')
    f.write('This document outlines the step-by-step process the system took to generate your crop recommendation.\n\n')
    
    step_num = 1
    
    for i in range(len(steps)):
        step = steps[i]
        content_str = ''.join(step['content']).strip()
        
        if step['type'] == 'Soil API Request':
            try:
                parsed = eval(content_str)
                f.write(f"### Step {step_num}: Checking Soil Conditions\n")
                f.write(f"**Action:** The system queried the SoilGrids database for the farm's location (Latitude: {parsed.get('lat')}, Longitude: {parsed.get('lon')}).\n")
                f.write(f"**Reason:** To understand the physical and chemical properties of the soil at your specific farm.\n\n")
                step_num += 1
            except:
                pass
                
        elif step['type'] == 'Soil API Response':
            f.write(f"### Step {step_num}: Receiving Soil Data\n")
            f.write(f"**Result:** The system received detailed soil information including pH, nitrogen, and clay percentage levels to base its recommendations on.\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Request' and 'query planner' in content_str:
            f.write(f"### Step {step_num}: Planning the Research Strategy\n")
            f.write(f"**Action:** The AI Query Planner analyzed your inputs (season, budget, water source) and the soil data to figure out what external information it needed to search for.\n")
            f.write(f"**Reason:** To find live, localized data that might affect your farm (like ministerial decrees, fertilizer prices, and pest alerts).\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Response' and i > 0 and steps[i-1]['type'] == 'LLM Request' and 'query planner' in ''.join(steps[i-1]['content']):
            try:
                parsed = json.loads(content_str)
                f.write(f"### Step {step_num}: Formulating Search Queries\n")
                f.write(f"**Result:** The AI decided to search the web for the following topics:\n")
                for q in parsed:
                    f.write(f"- {q.get('text')} *(Why? {q.get('rationale')})*\n")
                f.write('\n')
                step_num += 1
            except:
                pass
                
        elif step['type'] == 'Web Search Request':
            try:
                parsed = eval(content_str)
                f.write(f"### Step {step_num}: Searching the Web\n")
                f.write(f"**Action:** The system searched the internet for: \"{parsed.get('query')}\"\n\n")
                step_num += 1
            except:
                pass
                
        elif step['type'] == 'Web Search Response':
            try:
                parsed = eval(content_str)
                f.write(f"### Step {step_num}: Search Results\n")
                f.write(f"**Result:** Found several articles and resources. Top results included:\n")
                for r in parsed.get('results', [])[:3]:
                    f.write(f"- [{r.get('title')}]({r.get('url')})\n")
                f.write('\n')
                step_num += 1
            except:
                pass
                
        elif step['type'] == 'LLM Request' and 'extract atomic facts' in content_str:
            f.write(f"### Step {step_num}: Extracting Facts from Search Results\n")
            f.write(f"**Action:** The AI read through the search results to pull out concrete, factual information relevant to your farm in Egypt.\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Response' and i > 0 and steps[i-1]['type'] == 'LLM Request' and 'extract atomic facts' in ''.join(steps[i-1]['content']):
            try:
                parsed = json.loads(content_str)
                if parsed:
                    f.write(f"### Step {step_num}: Facts Discovered\n")
                    f.write(f"**Result:** The AI extracted the following key facts:\n")
                    for f_item in parsed:
                        f.write(f"- {f_item.get('fact')} *(Confidence: {f_item.get('confidence')})*\n")
                    f.write('\n')
                step_num += 1
            except:
                pass
                
        elif step['type'] == 'Weather API Request':
            f.write(f"### Step {step_num}: Checking Climate and Weather Data\n")
            f.write(f"**Action:** The system queried the NASA POWER climate database.\n")
            f.write(f"**Reason:** To calculate Growing Degree Days (GDD) and understand temperature trends for your farm.\n\n")
            step_num += 1
            
        elif step['type'] == 'Weather API Response':
            f.write(f"### Step {step_num}: Receiving Climate Data\n")
            f.write(f"**Result:** The system received historical climate data to ensure the recommended crops can survive the typical temperatures during your growing season.\n\n")
            step_num += 1

        elif step['type'] == 'LLM Request' and 'audit' in content_str.lower():
            f.write(f"### Step {step_num}: Auditing Evidence\n")
            f.write(f"**Action:** The AI reviewed all the gathered evidence to identify any missing information, contradictions, or low-confidence data.\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Request' and 'score' in content_str.lower():
            f.write(f"### Step {step_num}: Scoring Crop Candidates\n")
            f.write(f"**Action:** The AI evaluated multiple crop options against your soil, climate, water source, and market factors to calculate a suitability score for each.\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Request' and 'scenario' in content_str.lower():
            f.write(f"### Step {step_num}: Stress-Testing Recommendations\n")
            f.write(f"**Action:** The AI tested the top crop candidates against potential negative scenarios like drought, pest outbreaks, or currency devaluation to see how resilient they are.\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Request' and 'final recommendation' in content_str.lower():
            f.write(f"### Step {step_num}: Formatting the Final Report\n")
            f.write(f"**Action:** The AI compiled the top recommended crops, expected revenues, and risks into a clear, farmer-friendly report.\n\n")
            step_num += 1
            
        elif step['type'] == 'LLM Response' and i > 0 and steps[i-1]['type'] == 'LLM Request' and 'final recommendation' in ''.join(steps[i-1]['content']).lower():
            try:
                parsed = json.loads(content_str)
                f.write(f"### Step {step_num}: Final Crop Recommendation Output\n")
                f.write(f"**Result:** The system produced the final plain-language recommendation text you see as the output.\n\n")
                step_num += 1
            except:
                pass

print('Done generating narrative flow')
