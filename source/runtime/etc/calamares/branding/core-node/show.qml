import QtQuick 2.0
import calamares.slideshow 1.0

Presentation {
    id: presentation

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#000000"

            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width * 0.76, 760)
                spacing: 18

                Image {
                    source: "bitcoin.png"
                    width: 74; height: 74
                    fillMode: Image.PreserveAspectFit
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Text {
                    text: "Installing Bitcoin Core Node"
                    color: "white"
                    font.pixelSize: 28
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    width: parent.width
                }

                Text {
                    text: "The selected drive is being prepared and Bitcoin Core Node is being copied."
                    color: "#c0c0c0"
                    font.pixelSize: 16
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    width: parent.width
                }

                Item { width: 1; height: 10 }

                Text {
                    text: "Preparing the drive   ·   Copying the system   ·   Configuring startup   ·   Checking the installation"
                    color: "#8f8f8f"
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    width: parent.width
                }
            }
        }
    }

    function onActivate() { presentation.currentSlide = 0 }
    function onLeave() { }
}
