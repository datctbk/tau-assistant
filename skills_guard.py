import re
import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

@dataclass
class GuardResult:
    is_safe: bool
    violations: List[str]

class SkillGuard:
    """Security scanner for agent skills to prevent execution of destructive routines."""
    
    DESTRUCTIVE_PATTERNS = [
        # File destruction
        (r"rm\s+-r?[fF]", "Recursive forceful file deletion (rm -rf)"),
        (r"mkfs\.", "File system creation command"),
        (r"dd\s+if=", "Low-level block copying (dd)"),
        (r">\s*/dev/(sd[a-z]|nvme)", "Raw disk writes"),
        
        # System disruption
        (r"(shutdown|reboot|halt|poweroff)", "System state disruption"),
        (r"chmod\s+.*777", "Insecure global write permissions"),
        (r"chown\s+-R\s+root", "Recursive root ownership takeover"),
        
        # Network exfiltration
        (r"(curl|wget)\s+.*(-X\s*POST|-d)", "Unverified external POST request/data upload"),
        (r"nc\s+-e", "Netcat reverse shell"),
        (r"/dev/tcp/", "Bash reverse shell"),
    ]
    
    @classmethod
    def scan_markdown(cls, markdown_content: str) -> GuardResult:
        """Scan a markdown document (skill) for potential unsafe commands within codeblocks."""
        violations = []
        
        # Extract only code block contents
        code_blocks = re.findall(r"```[^\n]*\n(.*?)```", markdown_content, re.DOTALL)
        
        for block in code_blocks:
            for pattern, reason in cls.DESTRUCTIVE_PATTERNS:
                if re.search(pattern, block, re.IGNORECASE):
                    if reason not in violations:
                        violations.append(reason)
                        
        return GuardResult(
            is_safe=len(violations) == 0,
            violations=violations
        )
