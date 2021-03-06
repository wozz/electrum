##Electrum - lightweight Bitcoin client

Licence: GNU GPL v3  
Author: thomasv@bitcointalk.org  
Language: Python  
Homepage: http://electrum.org/  


###INSTALL

```bash
sudo python setup.py install
```


###RUN

To start Electrum in GUI mode, type:

```bash
electrum
```

###HELP

Up-to-date information and documentation is on the wiki:
https://en.bitcoin.it/wiki/Electrum


###HOW OFFICIAL PACKAGES ARE CREATED

```bash
python mki18n.py
pyrcc4 icons.qrc -o gui/qt/icons_rc.py
python setup.py sdist --format=zip,gztar
```

####On Mac OS X:

```bash
# On port based installs
sudo python setup-release.py py2app

# On brew installs
ARCHFLAGS="-arch i386 -arch x86_64" sudo python setup-release.py py2app --includes sip
```

```bash
sudo hdiutil create -fs HFS+ -volname "Electrum" -srcfolder dist/Electrum.app dist/electrum-VERSION-macosx.dmg
```


###BROWSER CONFIGURATION

See http://electrum.org/bitcoin_URIs.html

