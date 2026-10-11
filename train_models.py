"""Train and save both machine-learning models. Run once after installing (setup.bat does this)."""
import json

from models import crop_recommender, yield_predictor

if __name__ == "__main__":
    print("Training crop recommendation model ...")
    cm = crop_recommender.train(save=True)["metrics"]
    print(json.dumps({k: v for k, v in cm.items() if k != "per_crop_f1"}, indent=2))

    print("\nTraining yield model (this can take a minute) ...")
    ym = yield_predictor.train(save=True)["metrics"]
    print(json.dumps(ym, indent=2))
    print("\nModels saved in models/saved/")
