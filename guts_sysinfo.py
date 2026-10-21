import os
import psutil
import platform

def get_top_ram_consuming_apps(limit: int = 5) -> str:
    """Calculates RAM usage grouped by application name (aggregates multi-process apps like Chrome/VSCode)."""
    try:
        app_memory = {}
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                pname = proc.info['name']
                if not pname:
                    continue
                pname = pname.replace('.exe', '').capitalize()
                rss_mb = proc.info['memory_info'].rss / (1024 * 1024)
                app_memory[pname] = app_memory.get(pname, 0.0) + rss_mb
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort apps by memory usage descending
        sorted_apps = sorted(app_memory.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        used_gb = mem.used / (1024 ** 3)
        free_gb = mem.available / (1024 ** 3)

        res = [f"📊 RAM Usage Breakdown ({mem.percent}% used - {used_gb:.1f}GB / {total_gb:.1f}GB):"]
        for rank, (app, mb) in enumerate(sorted_apps, 1):
            if mb >= 1024:
                res.append(f"{rank}. {app}: {mb/1024:.2f} GB")
            else:
                res.append(f"{rank}. {app}: {int(mb)} MB")
                
        res.append(f"Free Memory Available: {free_gb:.1f} GB")
        return "\n".join(res)
    except Exception as e:
        return f"Error analyzing RAM: {str(e)}"

def get_detailed_system_specs() -> str:
    """Returns complete PC specifications including CPU, RAM, OS, Disk, and Power status."""
    try:
        uname = platform.uname()
        cpu_pct = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count(logical=True)
        
        mem = psutil.virtual_memory()
        total_ram_gb = round(mem.total / (1024**3), 2)
        used_ram_gb = round(mem.used / (1024**3), 2)
        
        disk = psutil.disk_usage('/')
        disk_total_gb = round(disk.total / (1024**3), 1)
        disk_free_gb = round(disk.free / (1024**3), 1)
        
        battery = psutil.sensors_battery()
        bat_status = f"{battery.percent}% {'(Plugged In)' if battery.power_plugged else '(On Battery)'}" if battery else "Desktop PC"

        info = (
            f"💻 System Specs for Boss's PC:\n"
            f"• OS: {uname.system} {uname.release} ({uname.machine})\n"
            f"• CPU: {uname.processor or 'Intel/AMD Processor'} ({cpu_count} Threads) @ {cpu_pct}% Load\n"
            f"• RAM: {used_ram_gb} GB used out of {total_ram_gb} GB ({mem.percent}%)\n"
            f"• Main Disk Storage: {disk_free_gb} GB free out of {disk_total_gb} GB\n"
            f"• Power Status: {bat_status}"
        )
        return info
    except Exception as e:
        return f"Error fetching system specs: {str(e)}"