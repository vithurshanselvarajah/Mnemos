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
- Gating on Rockchip container which confirms its running on correct hardware

General
- Added manifest.json to repo root to facilitate improved download functionality and runtime validation of model integrity.
- Addition of buffalo_m as a nice middle ground

Notes
- Rockchip support has only been tested on RK3588. Performance between CPU buffalo_s and all rknn s,m,l models is idential. Better image can be run as a default at no performance cost. 