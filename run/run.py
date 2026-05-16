import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

_ORANGE = "\033[38;5;208m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_GREEN = "\033[92m"
_DIM = "\033[2m"

def _banner():
    print(f"\n{_ORANGE}{_BOLD}")
    print("    ██████╗ ██████╗ ██╗ ██████╗ ██╗███╗   ██╗")
    print("   ██╔═══██╗██╔══██╗██║██╔════╝ ██║████╗  ██║")
    print("   ██║   ██║██████╔╝██║██║  ███╗██║██╔██╗ ██║")
    print("   ██║   ██║██╔══██╗██║██║   ██║██║██║╚██╗██║")
    print("   ╚██████╔╝██║  ██║██║╚██████╔╝██║██║ ╚████║")
    print("    ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝")
    print(f"{_RESET}\n")

if __name__ == "__main__":
    _banner()
    print(f"   {_ORANGE}{'─' * 52}{_RESET}")
    print(f"   {_BOLD}Initializing ORIGIN AI...{_RESET}\n")

    root = sys.argv[1] if len(sys.argv) > 1 else "."
    project_name = os.path.basename(os.path.abspath(root)).upper() or "ORIGIN_AI"

    try:
        from Models.qwen import qwen
        from terminal.ui import launch

        print(f"   {_GREEN}✓{_RESET}  {_BOLD}Qwen model loaded{_RESET}")
        print(f"   {_GREEN}✓{_RESET}  {_BOLD}Terminal UI ready{_RESET}")
        
    except ImportError as e:
        print(f"   {_ORANGE}✗{_RESET}  Error importing modules: {e}")
        print(f"   {_DIM}Make sure Models/qwen.py exists and .env has HC_API set{_RESET}\n")
        sys.exit(1)

    def ai_callback(prompt: str) -> str:
        try:
            if prompt.strip().startswith("/"):
                cmd = prompt.strip().lower().split()[0]

                if cmd == "/help":
                    return(
                        "ORIGIN AI Terminal Commands\n\n"
                        "  /help       Show this message\n"
                        "  /clear      Clear conversation (refresh UI)\n\n"
                        "Type anything else to chat with ORIGIN AI."
                    )
                elif cmd == "/clear":
                    return "Conversation cleared."
                else:
                    return f"Unkown command '{cmd}'. Type /help for commands."
            
            response = qwen(prompt)
            return response
        
        except Exception as e:
            return f"Error: {str(e)}"
    
    print(f"\n   {_ORANGE}{'─' * 52}{_RESET}")
    print(f"   {_GREEN}{_BOLD}✓  All systems ready.{_RESET}")
    print(f"   {_DIM}Launching terminal UI...{_RESET}")
    print(f"   {_ORANGE}{'─' * 52}{_RESET}\n")

    import time
    time.sleep(0.5)

    try:
        launch(
            ai_callback = ai_callback,
            root_dir = root,
            project_name = project_name,
        )
    except KeyboardInterrupt:
        pass

    finally:
        print(f"\n{_ORANGE}ORIGIN AI offline.{_RESET}\n")
        
