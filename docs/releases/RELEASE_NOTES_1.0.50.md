# Safeer OS za Windows 1.0.50

**Firefox ostane za Ščitom.** Firefox lahko sam vklopi DNS prek HTTPS in potem oglasne in nevarne domene razreši mimo filtra Ščit. Prej vpraša za domeno `use-application-dns.net`; Ščit zdaj odgovori, da je ni, zato Firefox ostane pri filtriranem sistemskem DNS (razen če si DNS prek HTTPS vklopil sam). To se ne šteje med blokirane oglase.

**Ščit ne utihne več.** Če je program odnehal, preden je Ščit odgovoril, je Windows na naslednjem branju javil napako 10054 in Ščitov poslušalec se je ustavil. Windows je nato vsako ime čakal okoli sekundo in ga razrešil mimo filtra. Zdaj poslušalec teče naprej. Preverjeno: po 20 takih odjemalcih Ščit še vedno odgovori v 2 ms.
