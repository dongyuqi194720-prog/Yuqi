import subprocess


MODEL = "/home/baixin/models/Qwen3VL-2B-Instruct-Q4_K_M.gguf"
MMPROJ = "/home/baixin/models/mmproj-Qwen3VL-2B-Instruct-F16.gguf"
LLAMA_MTMD = "/home/baixin/llama.cpp/build/bin/llama-mtmd-cli"


def observe_image(image_path, prompt="请描述这张图片中的界面内容。"):
    result = subprocess.run(
        [
            LLAMA_MTMD,
            "-m", MODEL,
            "--mmproj", MMPROJ,
            "--image", str(image_path),
            "-p", prompt,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    print(observe_image("/tmp/v6_window.png"))
