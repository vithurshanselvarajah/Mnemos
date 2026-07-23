Mnemos-Frontend
- New model download interface. 

Mnemos-Backend
- split into cpu, rockchip & nvidea variants
- initial beta support has been built for rockchip
- docker compose files have been updated to support  
- warmup has been configured so on rockchip it runs a dummy image to fully initialise the model. 
- very initial work towards nvidea support has begun. This will take time as i cannot install linux on my Nvidea PC. 
- Runtime validation of models has been added as default
- Check for manifest on container launch. Being unable to download the manifest leads to exponential retry logic. 
- Gating on rockchip container which confirms its running on correct hardware
- Introduced support for automated scaling of rockchip NPU cores. Mnemos will take advantage of multiple cores. 

General
- Added manifest.json to repo root to facilitate improved download functionality and runtime validation of model integrity.
- Addition of buffalo_m as a nice middle ground

Notes
- Rockchip support has only been tested on RK3588. Performance between CPU buffalo_s and all rknn s,m,l models is identical. Better model can be run as a default at no performance cost which is a benefit.
- NPU scaling currently splits 1 image across 3 cores. Some performance testing is pending to see if its more efficient to do 1 image per core. However normal usecase will be scanning a single image on identify. 