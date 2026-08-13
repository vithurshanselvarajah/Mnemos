Mnemos-Frontend
- New model download interface. 
- Add cache busting mechanism to certain static files
- Fix json response showing when deleting images from persons.
- Pairing key is now removed from API key list to prevent accidental deletion. 
- Add ability to re-pair backend if key is recycled or backend is deleted. 

Mnemos-Backend
- split into cpu, rockchip & nvidea variants
- Initial beta support has been built for rockchip
- Initial alpha support has been built of Nvidia
- docker compose files have been updated to support  
- warmup has been configured so on rockchip it runs a dummy image to fully initialise the model. 
- very initial work towards nvidea support has begun. This will take time as i cannot install linux on my Nvidea PC. 
- Runtime validation of models has been added as default
- Check for manifest on container launch. Being unable to download the manifest leads to exponential retry logic. 
- Gating on rockchip container which confirms its running on correct hardware
- Introduced support for automated scaling of rockchip NPU cores. Mnemos will take advantage of multiple cores. 
- Added tests for frontend and backend variants. 

General
- Added manifest.json to repo root to facilitate improved download functionality and runtime validation of model integrity.
- Addition of buffalo_m as a nice middle ground
- Added Docs
- Implemented Wiki Sync
- Implemented Backup and Restore functionality
- Align changes with Mnemos-HA 

Notes
- Rockchip support has only been tested on RK3588. Performance between CPU buffalo_s and all rknn s,m,l models is identical. Better model can be run as a default at no performance cost which is a benefit.
- NPU scaling currently splits 1 image across 3 cores. Some performance testing is pending to see if its more efficient to do 1 image per core. However normal usecase will be scanning a single image on identify. 