from fastapi import APIRouter
import psutil, platform, socket, time, datetime

router = APIRouter()

# Track uptime
start_time = time.time()

@router.get("/health")
def health_check():
    # --- SYSTEM METRICS ---
    cpu_usage = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_seconds = time.time() - start_time
    uptime_hours = round(uptime_seconds / 3600, 2)
    net_io = psutil.net_io_counters()
    connections = psutil.net_connections(kind="inet")

    return {
        "metrics": {
            "cpu_usage_percent": cpu_usage,
            "memory_percent": memory.percent,
            "memory_used_mb": round(memory.used / (1024 * 1024), 2),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "uptime_hours": uptime_hours,
            "bytes_sent_mb": round(net_io.bytes_sent / (1024 * 1024), 2),
            "bytes_recv_mb": round(net_io.bytes_recv / (1024 * 1024), 2),
            "active_connections": len(connections),
        },
        "server_info": {
            "hostname": socket.gethostname(),
            "ip": socket.gethostbyname(socket.gethostname()),
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "timestamp": datetime.datetime.now().isoformat(),
        },
        "guide": {
            "🔑 CPU Usage": {
                "meaning": "How much of your CPU is being used.",
                "what_to_look_for": {
                    "<70%": "Healthy",
                    "70–90%": "Busy, monitor closely",
                    ">90%": "Bottleneck (app may slow down, requests can time out)"
                },
                "use_case": "If FastAPI responds slowly, check here first."
            },
            "🔑 Memory Usage": {
                "meaning": "How much RAM is consumed by processes.",
                "what_to_look_for": {
                    "<70%": "Healthy",
                    "70–90%": "Risk of swapping to disk (slow)",
                    ">90%": "Likely memory leaks or too many processes"
                },
                "use_case": "If server crashes or gets killed (OOM), check memory."
            },
            "🔑 Disk Usage": {
                "meaning": "Storage space used on the system.",
                "what_to_look_for": {
                    "<70%": "Fine",
                    "70–90%": "Monitor",
                    ">90%": "Danger (logs, DB writes, uploads may fail)"
                },
                "use_case": "If app stores logs/files, low disk will break it."
            },
            "🔑 Uptime": {
                "meaning": "How long the server has been running.",
                "what_to_look_for": {
                    "short": "Unexpected restarts = crashes or instability",
                    "long": "Stable system"
                },
                "use_case": "If container/server keeps restarting, uptime will show it."
            },
            "🔑 Network Stats": {
                "meaning": "Traffic and active connections.",
                "what_to_look_for": {
                    "sudden_spike": "Possible attack or heavy load",
                    "too_many_connections": "DoS attack or sockets not closing"
                },
                "use_case": "If users can’t connect, check if connections are maxed out."
            },
            "🔑 Server Info": {
                "meaning": "Basic system identity and versioning.",
                "use_case": "Useful in debugging multi-server setups or compatibility."
            }
        }
    }
