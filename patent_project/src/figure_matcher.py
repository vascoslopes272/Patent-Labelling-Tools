import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image
import cv2
import numpy as np
import json
import re
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VLMMatcher:
    """
    A class to find and extract figures from patent drawings using a Vision-Language Model.
    """
    def __init__(self, model_id="Qwen/Qwen2.5-VL-7B-Instruct"):
        """
        Initializes the VLMMatcher, loading the specified model and tokenizer.
        """
        logger.info(f"Loading model: {model_id}")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")

        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        
        logger.info("Model loaded successfully.")

        self.prompt_template = (
            "You are a document analysis assistant. Your task is to analyze the provided patent drawing page "
            "and identify all individual sub-figures or distinct schematic blocks. "
            "For each identified figure, you must: "
            "1. Provide its bounding box as relative coordinates [x1, y1, x2, y2], where (0,0) is top-left and (1,1) is bottom-right. "
            "2. Identify the associated text label (e.g., 'FIG. 1', 'FIG. 10'). If no label is found, use null. "
            "Return your findings as a clean, raw JSON object and nothing else. Do not add explanations or markdown."
            'Example: {"figures": [{"box_2d": [0.1, 0.1, 0.4, 0.4], "label": "FIG. 1"}]}'
        )

    def _find_json_in_response(self, text: str) -> dict | None:
        """
        Extracts a JSON object from the model's text response.
        """
        # Look for ```json ... ``` markdown block
        match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        json_str = match.group(1) if match else text

        # Find the start of the JSON object
        json_start = json_str.find('{')
        if json_start == -1:
            logger.error("Could not find start of JSON object in response.")
            return None
        
        json_str = json_str[json_start:]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            logger.debug(f"Problematic JSON string: {json_str}")
            return None

    def _parse_figure_number(self, label: str | None) -> str | None:
        """
        Parses a figure number from a label string. e.g., "FIG. 1A" -> "1A".
        """
        if not label:
            return None
        match = re.search(r'(?:FIG|FIGURE)[\s.]*(\d+[A-Z]?)', label, re.IGNORECASE)
        return match.group(1) if match else None

    def process_image(self, image_path: Path, patent_id: str, output_dir: Path):
        """
        Processes a single patent drawing, extracts figures, and saves them.
        """
        if not image_path.exists():
            logger.error(f"Image file not found: {image_path}")
            return

        logger.info(f"Processing {image_path} for patent {patent_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        image = Image.open(image_path)
        image_width, image_height = image.size

        # Format the prompt for the Qwen-VL model
        messages = [{"role": "user", "content": [{"type": "text", "text": self.prompt_template}, {"type": "image"}]}]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)

        # Generate response
        with torch.no_grad():
            outputs = self.model.generate(**inputs, max_new_tokens=1024, do_sample=False, images=[image])
        
        response_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Clean up response to get only the generated part
        # This is a common pattern for many models, adjust if needed
        response_text = response_text.split("assistant
")[-1].strip()

        logger.info(f"Model Response: {response_text}")

        # Parse the JSON response
        parsed_json = self._find_json_in_response(response_text)
        if not parsed_json or 'figures' not in parsed_json:
            logger.warning(f"No valid figures JSON found for {patent_id}.")
            return

        # Process and save each figure
        unlabeled_idx = 0
        for i, fig_data in enumerate(parsed_json['figures']):
            box = fig_data.get('box_2d')
            label = fig_data.get('label')

            if not box or len(box) != 4:
                logger.warning(f"Skipping figure {i} due to invalid bounding box data.")
                continue

            # Convert relative coordinates to absolute pixel coordinates
            x1 = int(box[0] * image_width)
            y1 = int(box[1] * image_height)
            x2 = int(box[2] * image_width)
            y2 = int(box[3] * image_height)

            # Crop the figure using OpenCV
            img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            cropped_img = img_cv[y1:y2, x1:x2]

            if cropped_img.size == 0:
                logger.warning(f"Skipping figure {i} due to empty crop. Box: {[x1, y1, x2, y2]}")
                continue

            # Determine filename
            fig_num = self._parse_figure_number(label)
            if fig_num:
                # Pad with leading zero if it's a single digit number, e.g., 1A -> 01A
                num_part = re.match(r'(\d+)', fig_num).group(1)
                if len(num_part) == 1:
                     fig_num_padded = '0' + fig_num
                else:
                    fig_num_padded = fig_num
                
                # Format final number to be 3 chars minimum, e.g., 01A -> 001A is not ideal.
                # Let's stick to a simpler {patent_id}_F{number}.png
                # User wants F{number:03d}. This implies integer. 1A is not int.
                # Let's extract just the number part for the filename.
                
                numeric_part_match = re.search(r'\d+', fig_num)
                if numeric_part_match:
                    numeric_part = int(numeric_part_match.group(0))
                    filename = f"{patent_id}_F{numeric_part:03d}.png"
                else:
                    # Fallback for labels like 'FIG. A'
                    unlabeled_idx += 1
                    filename = f"{patent_id}_Fu{unlabeled_idx:03d}.png"
            else:
                unlabeled_idx += 1
                filename = f"{patent_id}_Fu{unlabeled_idx:03d}.png"
            
            save_path = output_dir / filename
            cv2.imwrite(str(save_path), cropped_img)
            logger.info(f"Saved figure to {save_path}")

if __name__ == '__main__':
    # Example usage for testing
    # Create a dummy image and directories for testing purposes
    
    test_project_dir = Path('./test_project')
    test_image_dir = test_project_dir / 'raw_images' / 'test_patent'
    test_output_dir = test_project_dir / 'matched'
    test_image_path = test_image_dir / 'drawing.png'

    test_image_dir.mkdir(parents=True, exist_ok=True)
    test_output_dir.mkdir(parents=True, exist_ok=True)

    # Create a simple dummy image with two squares and text
    dummy_image = np.ones((600, 800, 3), dtype=np.uint8) * 255
    # Square 1 (FIG. 1)
    cv2.rectangle(dummy_image, (50, 50), (350, 250), (0,0,0), 3)
    cv2.putText(dummy_image, 'FIG. 1', (150, 280), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
    # Square 2 (FIG. 2)
    cv2.rectangle(dummy_image, (450, 50), (750, 250), (0,0,0), 3)
    cv2.putText(dummy_image, 'FIG. 2', (550, 280), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
    # Unlabeled Square
    cv2.rectangle(dummy_image, (50, 350), (350, 550), (0,0,0), 3)
    
    cv2.imwrite(str(test_image_path), dummy_image)

    print("--- Running VLMMatcher Test ---")
    print("NOTE: This test requires a GPU and will download the model if not cached.")
    
    # This test will be very slow and resource-intensive if you run it.
    # It is provided here as a complete, runnable example.
    # try:
    #     matcher = VLMMatcher()
    #     matcher.process_image(
    #         image_path=test_image_path,
    #         patent_id='test_patent',
    #         output_dir=test_output_dir / 'test_patent'
    #     )
    #     print("--- Test Complete ---")
    #     print(f"Test outputs saved in: {test_output_dir / 'test_patent'}")
    # except Exception as e:
    #      print(f"Test failed. This is expected if you don't have a suitable GPU environment.")
    #      print(f"Error: {e}")

    print("src/figure_matcher.py has been created. The main execution block contains a test case.")
    print("To run the test, uncomment the try/except block in the 'if __name__ == '__main__':' section.")
