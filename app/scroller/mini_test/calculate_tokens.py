import re
import collections

log_path = r'c:\4_1 capstone\backend\app\logs\2026-03-18\info.log'

agent_tokens = collections.defaultdict(lambda: {"prompt": 0, "completion": 0})
total_prompt = 0
total_completion = 0
total_cost_estimate = 0

with open(log_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    match = re.search(r"📊 \[Token Usage\] Node Increment: Prompt=(\d+), Completion=(\d+)", line)
    if match:
        p = int(match.group(1))
        c = int(match.group(2))
        total_prompt += p
        total_completion += c
        
        # 해당 프린트가 어떤 에이전트에서 발생했는지 유추하기 위해 앞뒤 10줄 스캔
        agent_name = "Unknown"
        
        # 먼저 뒤쪽을 스캔 (대부분 토큰 로그 직후 SUCCESS/INFO가 찍힘)
        for j in range(i+1, min(i+10, len(lines))):
            next_line = lines[j]
            if "[JudgeAgent]" in next_line or "agent_judge" in next_line:
                agent_name = "JudgeAgent"
                break
            elif "[EditorAgent]" in next_line or "agent_editor" in next_line:
                agent_name = "EditorAgent"
                break
            elif "[WriterAgent]" in next_line or "agent_writer" in next_line:
                agent_name = "WriterAgent"
                break
            elif "[ClusterAgent" in next_line or "agent_cluster" in next_line:
                agent_name = "ClusterAgent"
                break
            elif "[ScoutAgent" in next_line or "agent_scout" in next_line:
                agent_name = "ScoutAgent"
                break
                
        # 못 찾았으면 앞쪽을 스캔
        if agent_name == "Unknown":
            for j in range(i-1, max(-1, i-10), -1):
                prev_line = lines[j]
                if "[JudgeAgent]" in prev_line or "agent_judge" in prev_line:
                    agent_name = "JudgeAgent"
                    break
                elif "[EditorAgent]" in prev_line or "agent_editor" in prev_line:
                    agent_name = "EditorAgent"
                    break
                elif "[WriterAgent]" in prev_line or "agent_writer" in prev_line:
                    agent_name = "WriterAgent"
                    break
                elif "[ClusterAgent" in prev_line or "agent_cluster" in prev_line:
                    agent_name = "ClusterAgent"
                    break
                elif "[ScoutAgent" in prev_line or "agent_scout" in prev_line:
                    agent_name = "ScoutAgent"
                    break
                    
        agent_tokens[agent_name]["prompt"] += p
        agent_tokens[agent_name]["completion"] += c

out_path = r'c:\4_1 capstone\backend\token_report.txt'
with open(out_path, 'w', encoding='utf-8') as fout:
    fout.write("\n" + "="*50 + "\n")
    fout.write("📊 에이전트별 토큰 사용량 분석 (오늘자 로그 총합)\n")
    fout.write("="*50 + "\n")
    for agent, usage in sorted(agent_tokens.items(), key=lambda x: x[1]['prompt'] + x[1]['completion'], reverse=True):
        p = usage['prompt']
        c = usage['completion']
        t = p + c
        fout.write(f"🔹 {agent:<15} : Prompt: {p:>10,} | Completion: {c:>10,} | Total: {t:>10,}\n")

    t_p = total_prompt
    t_c = total_completion
    t_t = t_p + t_c

    fout.write("-" * 50 + "\n")
    fout.write(f"🌟 전체 총합계     : Prompt: {t_p:>10,} | Completion: {t_c:>10,} | Total: {t_t:>10,}\n")
    fout.write("=" * 50 + "\n")

